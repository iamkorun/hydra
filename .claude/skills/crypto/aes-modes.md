# AES Mode Attacks Playbook

## ECB — detected by repeating ciphertext blocks

**Signal:** Ciphertext has 16-byte blocks that repeat. Or the challenge script uses `AES.new(key, AES.MODE_ECB)`.

**Attacks:**
- **ECB oracle (encrypt):** if an oracle encrypts `prefix || user_input || secret`, you can byte-at-a-time recover `secret`:
  1. Send `"A" * (block_size - 1)` → observe block containing first byte of secret.
  2. Brute-force that first byte by enqueueing `"A"*15 + candidate` and comparing.
  3. Shift alignment, repeat for each byte.
- **Block shuffling:** since ECB is deterministic per block, you can rearrange cipher blocks to craft arbitrary plaintext layouts if you control alignment (e.g., admin=true).

## CBC — bit flipping

**Signal:** `AES.MODE_CBC`, and the application decrypts attacker-controlled ciphertext.

**Attack (bit flip):** Flipping a byte of ciphertext block `C[i-1]` flips the same byte of plaintext block `P[i]` (while corrupting `P[i-1]`). If you know plaintext `P[i]` and want `P'[i]`:
```python
C_prev_new = bytes(a ^ b ^ c for a, b, c in zip(C_prev, P_known, P_target))
```
If there's a per-block integrity check, this won't work — try padding oracle instead.

## CBC padding oracle

**Signal:** Server returns different errors for "bad padding" vs "bad signature/other". Usually surfaces as a 400 vs 500.

**Attack:** Classic POODLE-style. Byte-at-a-time, from last byte of last block, XOR through:
```python
# For target plaintext byte at position i (1 = last byte of block):
# Set iv/prev-ciphertext byte so decryption yields PKCS#7 padding of value i.
# See any CBC padding oracle tutorial. In CTF, sqlmap-style automation is overkill;
# write 40 lines of python.
```
If `PadBuster` is installed: `padbuster <url> <cipher_b64> 16 -cookies 'auth=...'`.

## CTR / GCM — nonce reuse

**Signal:** Two ciphertexts encrypted with the same key AND same nonce (sometimes called "two-time pad").

**Attack:** `c1 XOR c2 = p1 XOR p2`. With any crib for `p1`, recover `p2`. Use frequency analysis on English or brute-force via known prefixes.

## Key stream recovery from known plaintext

If you know `p1` and have `c1`, then keystream `k = p1 XOR c1`, and any `c2` encrypted under the same (key, nonce) decrypts as `c2 XOR k`. Useful when the challenge gives you a "login" ciphertext and a "secret" ciphertext encrypted with the same nonce.
