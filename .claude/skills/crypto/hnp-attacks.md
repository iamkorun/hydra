# Hidden Number Problem (HNP) attack playbook

HNP is the generic pattern: some secret `x` is revealed *partially* —
top bits, low bits, a modular reduction, a few most-significant bits
of `x*g` for a known `g`. Recover `x` from the leaks. Many CTF
challenges are HNP in disguise:

| Challenge shape | What's leaked | Typical unknown size |
|---|---|---|
| ECDSA nonce reuse / biased nonces | top bits of `k` per signature | 2^64–2^128 total across 30+ signatures |
| EC point RNG disclosure (Blessed-class) | top bits of point x-coord | 2^32–2^48 per point |
| RSA partial plaintext | top or bottom bits of `m` | 2^128–2^256 (needs Coppersmith) |
| Debiased LCG / MT state | low bits of state | 2^32–2^64 |

## Decision tree: brute vs. lattice vs. algebra

**Step 1. Estimate the unknown size.** How many bits total? That
single number decides the attack class.

```
unknown ≤ 2^32   → brute force in C + GMP. Finishes in minutes.
unknown ≤ 2^40   → brute force + a cheap prefilter (Jacobi, Legendre,
                   parity) to cut the candidate set.
unknown ≤ 2^48   → hybrid: enumerate 16 bits, lattice-reduce the rest.
unknown > 2^48   → lattice (LLL / BKZ / flatter) on an HNP lattice.
                   Needs ≥ (n / biased_bits) signatures/samples.
```

**Step 2. Check feasibility of the brute route FIRST, every time.**
Before writing any lattice code, compile and run
`exploits/crypto/ecc_hnp_search.c` (or its RSA/ECDSA variant). If the
search space fits, this is the fastest route — no fiddly matrix
parameters to tune, no "the lattice didn't reduce enough" failure
mode.

For Blessed-class ECC leaks: replace `P_STR`, `A_STR`, `B_STR` with
the challenge curve, and `X_HIGH_STR` with the disclosed top bits.
Compile with `-O3 -march=native -lgmp`. A 2^32 scan takes ~4 min.

**Step 3. Collect data from the remote FIRST.** HNP attacks need
samples. Write a short Python + `pwntools.remote` or raw socket
loop that records every disclosed sample into a `./work/samples.json`
file. **Do this before any attack code** — you can't recover what
you haven't observed. The phase-3 + phase-4 Blessed failures both
had the attack infrastructure ready but never collected a single
remote sample.

```python
# ./work/collect.py — template
import json, socket
from pathlib import Path

def recv_until(sock, needle):
    buf = b""
    while needle not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf += chunk
    return buf

def main():
    samples = []
    with socket.create_connection(("HOSTNAME", PORT)) as s:
        for _ in range(N_SAMPLES):
            # Send the request that causes a disclosure
            s.sendall(b"...\n")
            reply = recv_until(s, b"...")
            samples.append(reply.decode("latin-1", "replace"))
    Path("samples.json").write_text(json.dumps(samples))
    print(f"saved {len(samples)} samples")

if __name__ == "__main__":
    main()
```

Run it. Commit the samples to `./work/`. Then analyze.

**Step 4. Lattice route, if needed.**  Use `fpylll` (pre-installed):

```python
from fpylll import LLL, IntegerMatrix

M = IntegerMatrix(n+1, n+1)
# ... build HNP matrix: diagonal = modulus, last row = known coefficients
L = LLL.reduction(M)
# Walk short vectors for candidate x
```

For the RSA HNP variant (Boneh-Durfee, small d, partial known bits),
use `flatter` when fpylll is too slow:

```bash
# flatter is in PATH. Feed it an IntegerMatrix via stdin.
```

## Budget

- Enumerate brute-force feasibility: 1 Bash call, 1 tool_use.
- Remote sample collection: 1 Write + 1 Bash, 2 tool_uses.
- Attack execution: depends on the route. Cap brute attempts at
  10 minutes of CPU; if nothing surfaces, switch to the lattice.

## Stop conditions

- Samples collected ≥ lattice threshold AND attack produces a
  candidate that verifies against a known-good response → ship it.
- No candidate after brute exhausts AND lattice gives garbage → the
  leak model is wrong. Re-read the challenge source; what you thought
  was "top 224 bits of x" might be "top 224 bits of x*G.y" or
  similar. One step back.
