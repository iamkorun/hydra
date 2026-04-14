# ECC Attacks Playbook

ECC is not "it's ECC so it's hard." The hard thing is solving DLP on a *correctly* parameterized curve. If the author made any of a dozen mistakes — singular/anomalous curve, tiny subgroup, small embedding degree, missing on-curve check, reused ECDSA nonce, biased `k` — the problem collapses from "254-bit DLP" to "one-liner." This skill is the decision tree. The image has pycryptodome, sympy, gmpy2, fpylll, flatter — **no sagemath**; adapt or shell out.

## Layer 0 — Identify the flaw before computing anything

Before *any* DLP work, enumerate the curve's structural weaknesses. Most CTF ECC challenges fail at Layer 0.

```python
# Parse curve params: usually given as p, a, b, Gx, Gy, n (group order), h (cofactor).
# If only p, a, b, G given → compute #E yourself (Schoof for big p is unavailable without sage;
# for small p use sympy's naive point counting; for production-size p the author WILL have given n).
from sympy import mod_inverse, gcd, isprime, factorint, discrete_log
import gmpy2

p, a, b = ...  # curve: y^2 = x^3 + a*x + b mod p
G  = (Gx, Gy) # base point
n  = ...       # order of G (if given)

# 1. Singular curve check
disc = (4 * a**3 + 27 * b**2) % p
print("singular?", disc == 0)

# 2. Anomalous check (requires #E; if n is prime and n == p, it's anomalous up to cofactor)
# Full curve order #E = n * h. If #E == p, Smart's attack applies.
print("anomalous?", (n * h) == p if 'h' in dir() else "need cofactor")

# 3. Pohlig-Hellman viability — factor n
print("n factored:", factorint(n, limit=10**7))  # smooth ⇒ deadly

# 4. Embedding degree (MOV). Smallest k s.t. n | p^k - 1.
k = None
for kk in range(1, 30):
    if pow(p, kk, n) == 1:
        k = kk; break
print("embedding degree k =", k)  # k ≤ 6 ⇒ MOV

# 5. On-curve enforcement (protocol-level) — see invalid-curve section below
```

Decision tree:

- `4a³ + 27b² ≡ 0 (mod p)` → **singular** (seconds to solve)
- `#E(Fp) = p` → **anomalous**, Smart's attack (polynomial time)
- `n` has small prime factors → **Pohlig-Hellman** per factor, CRT
- embedding degree `k ≤ 6` → **MOV/Frey-Rück**, transfer to `GF(p^k)` DLP
- server doesn't check `y² ≡ x³+ax+b`? → **invalid curve** (send low-order off-curve point)
- ECDSA with multiple signatures? → check for **nonce reuse** and **bias** (HNP)

---

## 1. Invalid curve attack

**Trigger:** Protocol where you send a point `(x,y)` and server computes `d·P = (d·x, d·y)` without verifying `(x,y)` lies on the advertised curve `E`. Common in custom TLS-like handshakes, DH-style key exchange.

**Key insight:** the scalar-mult formulas for `E: y²=x³+ax+b` only depend on `a` (not `b`). So any curve `E': y²=x³+ax+b'` is attacked by the same code path. Pick `b'` such that `E'` has a small-order point, send that point, recover `d mod ord`, repeat, CRT.

```python
from sympy import factorint, discrete_log
from sympy.ntheory.residue_ntheory import sqrt_mod

def make_weak_curve(p, a, target_order_factors):
    # Pick b' s.t. #E'(Fp) has target_order_factors as divisors.
    # In practice: generate random b', count points (small-curve only) or
    # use BOSS/mwrank; for CTF typically the author hands you the weak curves.
    ...

# Attack loop
residues = []
for (x, y), ord_prime in weak_points:  # (point on E' with order ell)
    server_out = send_point(x, y)       # = d*(x,y) mod E'
    d_mod_ell = discrete_log(ell, server_out, (x,y))  # baby-step giant-step
    residues.append((d_mod_ell, ord_prime))

# CRT all (d_mod_ell, ell) pairs. If product > n, we have d.
d = crt_combine(residues)
```

**Frequency:** shows up in ~15% of ECC challenges, especially "custom protocol" ones. Reference: Jager–Schwenk–Somorovsky 2015 (practical invalid curve attacks on TLS-ECDHE).

---

## 2. Singular curve

**Trigger:** `4a³ + 27b² ≡ 0 (mod p)`. The curve has a cusp or node.

**Attack:** Map the non-singular points to `(Fp, +)` (additive) or `Fp*` (multiplicative). DLP collapses.

- **Cusp** (double root of `x³+ax+b`): isomorphic to `(Fp, +)`. DLP becomes division mod p — trivial.
- **Node** (distinct roots but shared): isomorphic to `Fp*` or `Fp²*`. Use `sympy.discrete_log` (Pollard's rho or BSGS).

```python
from sympy import symbols, roots, discrete_log

# y^2 = x^3 + a*x + b with 4a^3 + 27b^2 = 0
# Translate so singular point is at x=0: find x0 s.t. 3x0^2 + a = 0 and x0^3 + a*x0 + b = 0
# Then y^2 = (x - x0)^2 * (x + 2x0)  → look at alpha = 2x0
x0 = -3 * b * pow(2 * a, -1, p) % p        # shift
alpha = (3 * x0) % p                         # discriminant of the quadratic factor

def phi(P):  # map E_ns(Fp) → Fp* or Fp
    x, y = P
    if alpha == 0:   # cusp → additive group
        return (x - x0) * pow(y, -1, p) % p
    # node → multiplicative: compute (y + sqrt(alpha)*(x-x0)) / (y - sqrt(alpha)*(x-x0))
    s = pow(alpha, (p + 1) // 4, p)  # if p ≡ 3 mod 4 and alpha is QR
    num = (y + s * (x - x0)) % p
    den = (y - s * (x - x0)) % p
    return num * pow(den, -1, p) % p

uG  = phi(G)
uQ  = phi(Q)
d   = discrete_log(p, uQ, uG)     # additive case: d = uQ * inverse(uG) mod p
```

**Frequency:** ~5-10% of ECC challenges (often the "looks normal, isn't" trap).

---

## 3. Anomalous curve (Smart's attack)

**Trigger:** `#E(Fp) = p`. Curve is called "anomalous" or "trace-one." Classic tell: problem gives you `p` and tells you `n = p`.

**Attack:** Lift `G` and `Q` to `Qp` (p-adic rationals), compute `p·G̃` and `p·Q̃`, take the y/x-ratio — that's the formal-group logarithm. Divide mod `p`.

Smart 1999: `O(log p)` complexity. Devastating.

```python
# NO sage. Implement Hensel lift + formal log manually (clean ~60 lines).
# Canonical python port: https://github.com/lukasgrochal/smart-attack (MIT, 2019)
# Or port-of-sage: https://gist.github.com/elliptic-shiho (search "smart's attack python")

def smarts_attack(E, p, G, Q):
    """
    E = (a, b) defining y^2 = x^3 + a*x + b over Fp, with #E(Fp) = p.
    Returns d s.t. Q = d*G mod E.
    """
    # Lift G, Q to E over Z/p^2 Z via Hensel:
    Gp2 = hensel_lift(G, E, p)
    Qp2 = hensel_lift(Q, E, p)
    # Scalar-multiply by p → result is in formal group (x-coord ≡ ∞ mod p).
    pG = scalar_mult_p2(p, Gp2, E, p*p)
    pQ = scalar_mult_p2(p, Qp2, E, p*p)
    # Formal log = -x/y  (for points in kernel of reduction mod p).
    phi = lambda P: (-P[0] * pow(P[1], -1, p*p)) % (p*p)
    lG = phi(pG) // p     # division by p lands us in Fp
    lQ = phi(pQ) // p
    d  = lQ * pow(lG, -1, p) % p
    return d
```

Or shell out to sage ad-hoc (pycryptodome has no lift):

```bash
# If Hydra lacks sage, run on host via docker (one-shot, ~30s):
docker run --rm -v $PWD:/work sagemath/sagemath:latest sage /work/smart.sage
```

**Frequency:** ~8% of ECC challenges — authors love this because it *looks* hopeless.

---

## 4. MOV / Frey-Rück attack

**Trigger:** Small embedding degree `k`: smallest `k` with `n | p^k - 1`. Tractable for `k ≤ 6`; definitely for `k ≤ 3`. Supersingular curves over Fp have `k = 2`.

**Attack:** Use the Weil or Tate pairing to map `E(Fp)[n]` into `GF(p^k)*`. Then the ECDLP becomes a finite-field DLP in `GF(p^k)*`, solvable by index calculus.

```python
# Pure-python pairing + index calc is heavy; use sage via docker OR port from:
#   https://github.com/jvdsn/crypto-attacks/blob/master/attacks/ecc/mov_attack.py (Jan de Snyder's repo)
# The attack goes:
#   1. Pick random T of order n on E(Fp^k) with e_n(G, T) ≠ 1
#   2. alpha = e_n(G, T)   in GF(p^k)*
#   3. beta  = e_n(Q, T)   in GF(p^k)*
#   4. d = discrete_log(beta, alpha) in GF(p^k)*  ← index calculus
```

When `k = 2` (supersingular), `GF(p²)` DLP is often tractable with sympy for small `p` or NFS-FF for big `p` (Hydra has no NFS-FF — use sage docker).

**Frequency:** ~10% of ECC challenges. Warning: FR is nearly always paired with "weird curve that happens to have `j = 0` or `j = 1728`" — those flags are instant tells.

Reference: https://github.com/jvdsn/crypto-attacks (comprehensive ECC attack zoo in pure python).

---

## 5. Small subgroup attack

**Trigger:** Base point `P` has small order (often `ord(P) < 2^40`). Can be accidental (weak `G`) or forced via cofactor — e.g., Curve25519 has cofactor 8 and points of order 2, 4, 8 exist. If the protocol doesn't clamp or check, you can send such a point.

**Attack:** Replace `G` with a point of tiny order `q | n`. Server computes `d·G'`. Solve `d mod q` with BSGS. Repeat across many `q`s, CRT.

```python
from sympy import discrete_log

small_q_residues = []
for q in small_order_subgroup_generators:
    Q_test = scalar_mult(d_unknown, q)   # server leaks this
    d_mod_q = discrete_log(q.order, Q_test, q)
    small_q_residues.append((d_mod_q, q.order))
# CRT (standard).
```

**Curve25519 cofactor-8 trap:** send a point of order 2/4/8 → leak `d mod 8`. Combined with other leaks, devastating.

**Frequency:** ~15% of ECC challenges, especially ones using Curve25519 in "implement your own DH."

---

## 6. Pohlig-Hellman

**Trigger:** `n = #E(Fp)` (or order of G) factors into small primes. "Smooth n." Test first: `factorint(n, limit=10**7)`.

**Attack:** Solve ECDLP modulo each prime factor `ell` of `n`, then CRT.

```python
from sympy import factorint, discrete_log

def pohlig_hellman_ecdlp(G, Q, n, point_add, scalar_mul):
    fac = factorint(n)
    residues = []
    for ell, e in fac.items():
        q = ell ** e
        # Reduce to subgroup of order q:
        Gp = scalar_mul(n // q, G)
        Qp = scalar_mul(n // q, Q)
        # Solve DLP in the order-q subgroup using BSGS or rho:
        # For small q, naive enumeration is fine; for q up to ~2^40, BSGS.
        d_mod_q = ecdlp_bsgs(Gp, Qp, q)
        residues.append((d_mod_q, q))
    # CRT
    from functools import reduce
    def crt(pairs):
        x, m = 0, 1
        for (xi, mi) in pairs:
            g = gcd(m, mi)
            assert (xi - x) % g == 0
            lcm = m * mi // g
            x = (x + m * ((xi - x) // g) * pow(m // g, -1, mi // g)) % lcm
            m = lcm
        return x
    return crt(residues)
```

**Frequency:** deadly whenever `n` is smooth. ~20% of ECC challenges have this as a secondary reduction step (e.g., after invalid curve, each weak curve needs P-H internally).

---

## 7. ECDSA nonce reuse — closed form key recovery

**Trigger:** Two ECDSA signatures `(r₁, s₁)`, `(r₂, s₂)` on different messages with `r₁ == r₂`. Same nonce `k` was used.

**Attack:** Recover `k`, then `d`, in 4 lines.

```python
from sympy import mod_inverse

# Given (r, s1, h1) and (r, s2, h2) where h_i = H(m_i) truncated to n bits, n = group order
k = (h1 - h2) * mod_inverse(s1 - s2, n) % n
d = (s1 * k - h1) * mod_inverse(r, n) % n

# Verify: pubkey should be d*G
```

Variant: if you suspect reuse but the `r`s are different, you may have *linear-relation* reuse (e.g., `k₂ = a*k₁ + b`). Try small relations.

**Frequency:** the top ECDSA CTF attack. ~40% of ECDSA challenges. Always check duplicate `r` first.

Reference: Nguyen–Shparlinski 2002; any ECDSA post-mortem.

---

## 8. ECDSA biased `k` — Hidden Number Problem (HNP)

**Trigger:** Many ECDSA signatures where `k` is biased — e.g., "top 4 bits of `k` are zero" (signer uses a narrow RNG), or lsb-leak from a timing/side-channel side-product. You have `m` signatures (usually 60–200) and a known bias.

**Attack:** Lattice reduction. Build a lattice where the short vector encodes `d` plus the `m` unknown low-bits of `k`. LLL + Babai's CVP (or BKZ for tighter bias).

```python
# Canonical Boneh-Durfee-style HNP lattice (Nguyen-Shparlinski 2003):
# For each sig i: s_i * k_i ≡ h_i + r_i * d  (mod n)
# With bias: k_i = 2^L * a_i + b_i, b_i known to be 0 (or small) and a_i ~ n/2^L bits.
# Rearrange:  a_i ≡ (s_i^{-1} * h_i / 2^L) + (s_i^{-1} * r_i / 2^L) * d   (mod n/2^L)
# Stack rows → CVP against target vector t.

from fpylll import IntegerMatrix, LLL, GSO
from fpylll.algorithms.bkz2 import BKZReduction

def hnp_attack(sigs, n, L):
    # sigs = [(h_i, r_i, s_i)], L = number of known LSB zero bits
    m = len(sigs)
    scale = 1 << L
    ts = [(pow(s, -1, n) * r % n) * pow(scale, -1, n) % n for (h, r, s) in sigs]
    us = [(pow(s, -1, n) * h % n) * pow(scale, -1, n) % n for (h, r, s) in sigs]

    B = IntegerMatrix(m + 2, m + 2)
    for i in range(m):
        B[i, i]      = n
    for i in range(m):
        B[m, i]      = ts[i]
    for i in range(m):
        B[m + 1, i]  = us[i]
    B[m, m]      = 1
    B[m + 1, m + 1] = n // scale

    LLL.reduction(B)
    # BKZ often needed for marginal bias:
    BKZReduction(B)(block_size=25)

    # Scan rows for one where last-but-one coord reveals d:
    for row in B:
        cand = row[m] % n
        if cand != 0 and verify(cand):   # verify d*G == pubkey
            return cand
```

Rules of thumb for bias `b` bits known:

- `b ≥ 7` and `m ≥ 100`: LLL suffices.
- `b ≥ 4` and `m ≥ 200`: BKZ-20 or BKZ-30.
- `b = 1`: use **flatter** (pre-installed) + BKZ-40. See Albrecht–Heninger "On Bounded Distance Decoding with Predicate" 2021, and the nonce-leak attack on NIST P-256 signatures in Ryan "Return of the Hidden Number Problem" (2019).

**Frequency:** ~12% of ECDSA challenges. Tell: challenge hands you 100+ sigs with a bias hint in the description.

Reference: Nils Anlauff & David Lazar, "Attacks on ECDSA"; https://github.com/bitlogik/lattice-attack (ready-made fpylll HNP tool).

---

## 9. ECDSA `(r, s)` malleability

**Trigger:** Verifier accepts `(r, s)` but not `(r, n-s)`, or vice versa. Or accepts both.

**Attack:** Given a valid sig `(r, s)`, produce a second valid sig `(r, n-s)` for the same message. Useful when an app uses signatures as idempotency keys or nonces (Bitcoin ecosystem famously).

```python
s_prime = (n - s) % n
# (r, s_prime) is also valid on the same (m, pubkey).
```

Similarly: some lax verifiers accept `(r mod n, s)` where `r` was never reduced → low-r malleability.

**Frequency:** ~3% on its own, but often a *piece* of a larger ECDSA chain (double-spend, replay, admin-takeover).

---

## 10. Fault attacks / invalid-signature forge

**Trigger:** Verifier doesn't check that intermediate points computed during `k*G` (or during signature verification's point reconstruction) lie on the curve. Related to #1 but in the *verify* path.

**Attack:** In `verify(m, r, s, Q)`, the verifier reconstructs `R = (s⁻¹·h)·G + (s⁻¹·r)·Q`. If we can induce a fault mid-computation (in practice via a carefully crafted public-key `Q` off-curve, or a twist-curve `Q`) to make `R.x == r` for *any* chosen `(r, s)`, the signature forges without knowing `d`.

Also: Biehl–Meyer–Müller 2000 fault model — a bit-flip during scalar mult leaks `d` bit-by-bit.

In CTF this usually surfaces as:

- "server verifies a sig but doesn't check pubkey on-curve" — forge by supplying Q on a twist with tiny order.
- "server verifies weirdly; try sending `(r, 0)` or `(0, s)`" — many impls crash or accept.

**Frequency:** ~5% of ECC challenges. Read the verify code, look for missing point-validation.

---

## ECDSA — pre-flight checklist (do this before inventing anything)

```python
# Given a list of (msg, r, s) tuples:

# 1. Nonce reuse — r collisions
from collections import Counter
r_counts = Counter(r for (_, r, _) in sigs)
if any(c > 1 for c in r_counts.values()):
    print("NONCE REUSE — use attack #7")

# 2. s-bit distribution — check for top-bit zeroing
import statistics
top_bits = [s >> (n.bit_length() - 8) for (_, _, s) in sigs]
if statistics.stdev(top_bits) < 30:
    print("BIASED k — use attack #8 (HNP)")

# 3. Weak r — zero, same as n, etc.
for (h, r, s) in sigs:
    if r == 0 or s == 0 or r == n or s == n:
        print("malformed sig — check #9/#10")

# 4. Small signatures count? If ≤ ~50, HNP infeasible; look for nonce reuse or side-channel.
```

---

## Tools available in Hydra image

| Tool | Use |
|------|-----|
| `pycryptodome` | `from Crypto.PublicKey import ECC` — parse PEM/DER, point arithmetic |
| `sympy` | `discrete_log` (BSGS, Pollard rho), `factorint`, `mod_inverse`, `sqrt_mod` |
| `gmpy2` | `mpz` for fast modular arithmetic; `iroot`, `powmod`, `invert` |
| `fpylll` | `LLL.reduction`, `BKZ.reduction`, `CVP.closest_vector` — HNP, Coppersmith |
| `flatter` | Drop-in faster LLL for rank > 40 lattices (HNP scales) |
| `pari/gp` | `gp -q -e "..."` — elliptic curve ops, `ellgroup`, `elllog`, factor |
| `RsaCtfTool` | Not ECC but its venv has some pure-python ECC helpers |
| `docker run sagemath/sagemath:latest` | Ad-hoc sage one-shots. Slow cold-start (~20s) but canonical for MOV/Smart's |

**No sagemath apt package** in the image (dropped from Ubuntu noble). `pip install sagemath` exists but pulls ~2GB; prefer docker for one-off `.sage` scripts. Tell the user if you're about to do this; it's not free.

**Pure-python ECC attack repos to port code from:**

- `jvdsn/crypto-attacks` — https://github.com/jvdsn/crypto-attacks — best-of-breed, MIT, has Smart, MOV, invalid-curve, HNP.
- `ashutosh1206/Crypton` — https://github.com/ashutosh1206/Crypton — canonical CTF crypto writeup repo.
- `defund/coppersmith` — lattice helpers, ECC isn't its focus but the lattice primitives transfer to HNP.
- `bitlogik/lattice-attack` — drop-in HNP + ECDSA bias solver with fpylll.

---

## Common traps

- **Curve conventions.** Short Weierstrass (`y² = x³ + ax + b`), Montgomery (`By² = x³ + Ax² + x`), Edwards (`x² + y² = 1 + dx²y²`). `ECC.construct()` in pycryptodome assumes short-Weierstrass; if challenge gives Montgomery params, convert first (there are closed-form maps). Curve25519 is Montgomery.
- **Cofactor `h`.** `#E = n*h`. Subgroup attacks hit cofactor. Curve25519 has `h=8`; secp256r1 has `h=1`. The author can't pull subgroup tricks when `h=1`, but anomalous still works.
- **`int` vs `gmpy2.mpz`.** For discrete log loops, `mpz` is 5-10x faster. Always cast: `mpz(x)`. For `sympy.discrete_log`, sympy internally uses Python int; for DLPs up to `~2^60`, still fine.
- **`sympy.discrete_log(n, a, b)` signature:** returns `x` such that `b^x ≡ a (mod n)`. Note argument order — `a` is the target, `b` is the base. Easy to swap and get a wrong answer silently.
- **Hash truncation in ECDSA.** `h = H(m)` is truncated to `n.bit_length()`. Many custom impls forget this; if your HNP lattice won't reduce, check the hash handling.
- **"Random" nonce isn't.** `k = H(d || m)` (deterministic RFC 6979) is NOT nonce-reuse-vulnerable, but is vulnerable to `d` extraction from a single sig if `H` is weak (biased output).
- **Pollard-rho vs BSGS.** For `order < 2^40`, either. For `2^40 – 2^80`, rho only. For `> 2^80`, you need a structural weakness (Layer 0) — plain DLP is infeasible.

---

## Stop conditions

Stop and reclassify / postmortem when:

1. All Layer-0 checks come back "structurally sound" AND the curve is a named standard (`secp256k1`, `secp256r1`, `Curve25519`) AND `n` is prime AND there are no ECDSA anomalies. This is not a solvable ECC challenge as posed — reread README, check for *protocol* bugs (replay, mixing channels, weak KDF afterward), or misclassified (could be protocol/web).
2. Layer-0 identified anomalous/MOV but the pure-python port won't converge in 10 minutes. Shell out to `docker run sagemath/sagemath:latest` — if even sage hits 30+ minutes, reclassify.
3. HNP lattice LLL returns but `d*G != pubkey` for all candidate rows. Verify bias assumption first, then increase `m` (more sigs) OR try BKZ with higher block size, OR switch to flatter. After 3 attempts, postmortem.
4. More than two re-dispatches from the orchestrator. Write `./work/postmortem.md` with what was tried and why.
