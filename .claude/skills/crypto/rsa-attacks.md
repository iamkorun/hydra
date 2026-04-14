# RSA Attacks Playbook

Classical-weakness attacks on textbook RSA. Each entry: *signal*, *attack*, *concrete commands/code*.

## Wiener's attack — small private exponent

**Signal:** `d` is small (`d < n^0.25`). Often: `e` is large (close to `n`), or "very small d" stated.

**Attack:** Continued-fraction expansion of `e/n` yields `k/d`. See `exploits/crypto/rsa_wiener.py`.

**Sanity check after:** verify `pow(c, d, n) == m_int` and `long_to_bytes(m_int)` looks flag-like.

## Hastad / low-exponent — small `e`, short `m`

**Signal:** `e = 3` (or small), multiple ciphertexts under different `n` with same `m` (broadcast), OR a single ciphertext where `m^e < n` (short message).

**Attack (single-ciphertext):** `m = iroot(c, e)` using gmpy2.
```python
from gmpy2 import iroot, mpz
m, exact = iroot(mpz(c), e)
```

**Attack (broadcast, ≥ e ciphertexts):** CRT combine, then cube-root.

See `exploits/crypto/rsa_hastad_small_e.py`.

## Common modulus

**Signal:** Same `n`, two different `e`s (`e1`, `e2`) where `gcd(e1,e2) = 1`, two ciphertexts.

**Attack:** `a*e1 + b*e2 = 1` via extended GCD. Then `c1^a * c2^b ≡ m (mod n)`. See `exploits/crypto/rsa_common_modulus.py`.

## Fermat factoring — close `p` and `q`

**Signal:** `|p - q|` is small (primes chosen too close). `n = p*q`.

**Attack:** Start from `a = ceil(sqrt(n))`, increment `a` while `a^2 - n` is not a perfect square.

See `exploits/crypto/rsa_fermat.py`.

## Batch GCD — shared primes across multiple moduli

**Signal:** You have 10+ public keys. Some share a prime factor.

**Attack:**
```python
import math
for i, ni in enumerate(ns):
    for nj in ns[i+1:]:
        g = math.gcd(ni, nj)
        if 1 < g < ni:
            print(f"found: {i} shares prime with another → p={g}")
```

## Franklin-Reiter / related messages

**Signal:** Two ciphertexts, same `n` and `e=3`, messages differ by a known linear relation: `m2 = m1 + delta`.

**Attack:** Requires sage / polynomial GCD. Template not in P1 — write from scratch using sage.

## Coppersmith's method

**Signal:** Partial knowledge of `m` or a prime factor. Small `e`, high bits of `p` known, etc.

**Attack:** sage's `small_roots` on the appropriate polynomial.

## Fallback — RsaCtfTool

When in doubt:
```bash
RsaCtfTool -n <N> -e <E> --publickey key.pem --uncipher <CT_HEX>
# or, for many attacks at once:
RsaCtfTool --publickey key.pem --attack all
```
Read its output carefully — it often names the weakness explicitly.

## Last-resort factoring

For small `n` (<512 bits), try:
```bash
# Use msieve or yafu if available, or sage's factor()
sage -c "print(factor($N))"
```
