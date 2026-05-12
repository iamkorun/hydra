# Phase-4 Hard Guards + Specialist Tools Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three false-positive failure modes observed in phase-4 (Blessed/Router-Web/Debug) AND lift hydra's general robustness on categories hydra has never seen, without overfitting to the specific challenges.

**Architecture:** Three layers. (1) **Python hard guards** in `hydra/flag_extractor.py` and `hydra/orchestrator.py` — drop the generic regex sweep, require a positive derivation signal, cross-check that the agent actually contacted the remote, and demote OOM-killed "solves" to `solved_uncertain`. These replace soft prose rules with mechanical enforcement and apply to every future challenge regardless of category. (2) **Docker image** — pre-install `sigrok-cli` + `libsigrokdecode4` so any hardware/signal challenge has a real decoder, ship a `sal2sigrok` converter script so the agent doesn't rewrite Saleae parsers from scratch, and install a shell wrapper that caps `analyzeHeadless` invocations so Ghidra can't swallow the token budget on any reverse-heavy challenge. (3) **Specialist references + templates** — add an HNP skill and brute-force C template usable by any HNP-class challenge (ECDSA nonce leaks, RSA partial-bit leaks, EC point partial disclosure), plus a skill doc for UART/SPI/I2C decoding that works for every future logic-capture challenge, not just Debug.

**Tech Stack:** Python 3.12, pytest, Docker/Ubuntu 24.04, sigrok-cli/libsigrokdecode, shell, C + GMP, numpy.

**Spec reference:** conversation thread in `ctf-try-out` session; phase-3 postmortem plan at `docs/superpowers/plans/2026-04-16-phase3-postmortem-fixes.md`; phase-4 logs at `<external HTB phase-4 logs>`.

---

## File Structure

```
hydra/
├── hydra/
│   ├── flag_extractor.py                              # Tasks 1 + 2
│   ├── remote_contact.py                              # Task 9 (NEW)
│   └── orchestrator.py                                # Tasks 9 + 10
├── tests/unit/
│   ├── test_flag_extractor.py                         # Tasks 1 + 2
│   ├── test_remote_contact.py                         # Task 9 (NEW)
│   └── test_orchestrator.py                           # Task 10
├── Dockerfile                                         # Tasks 4 + 5
├── docker/
│   ├── apt-packages.txt                               # Task 3
│   ├── ghidra-wrapper.sh                              # Task 4 (NEW)
│   └── bin/
│       └── sal2sigrok                                 # Task 5 (NEW, NEW DIR)
├── .claude/
│   ├── agents/
│   │   ├── forensics-specialist.md                    # Task 6
│   │   ├── misc-specialist.md                         # Task 6
│   │   └── crypto-specialist.md                       # Task 7
│   └── skills/
│       ├── hw/
│       │   └── uart-sigrok.md                         # Task 6 (NEW, NEW DIR)
│       └── crypto/
│           └── hnp-attacks.md                         # Task 8 (NEW)
└── exploits/
    └── crypto/
        └── ecc_hnp_search.c                           # Task 7 (NEW)
```

Ten tasks, one commit each. Tasks 1–2 + 9–10 run the existing pytest suite. Tasks 3–5 change the Docker image (rebuild outside this plan). Tasks 6–8 are prose + a C template; they don't need a build step.

---

## Task 1: flag_extractor — reject placeholder bodies (conservative: no identifier-only rule)

Phase-4 false positives came from three body shapes that slipped past the existing whitespace/url/REMINDER rejects:

1. `HTB{...}` — three literal dots, echoed from a README format spec.
2. `HTB{FakeFlagForTesting}` / `HTB{FlagForPreviousChallengePleaseIgnore}` — decoy strings baked into challenge binaries by authors.
3. `bit{bit_idx}` — a Python f-string source-code literal leaked via `cat`.

This task handles rejections 1 and 2 at the body level. Rejection 3 is covered architecturally by Task 2 (removing the generic stdout sweep), which is a cleaner fix than a body pattern that would also false-reject legitimate short flags (`picoCTF{welcome}`, training challenges).

**Files:**
- Modify: `hydra/flag_extractor.py`
- Modify: `tests/unit/test_flag_extractor.py`

- [ ] **Step 1: Add the failing tests (phase-4 regressions)**

Append to `tests/unit/test_flag_extractor.py`:

```python
# Phase-4 false-positive regressions.

def test_reject_all_dots_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "format: HTB{...}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_placeholder_fake_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "strings output: HTB{FakeFlagForTesting}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_placeholder_ignore_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "decoy: HTB{FlagForPreviousChallengePleaseIgnore}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_placeholder_in_flag_file(tmp_path: Path):
    # Even if written to flag.txt, a placeholder-body flag is rejected.
    (tmp_path / "flag.txt").write_text("HTB{placeholder_value}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag is None

def test_accept_realistic_short_flag_with_digits(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: HTB{a1B2c3}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{a1B2c3}"

def test_accept_real_htb_underscored_flag(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: HTB{4n_unusual_s1ght1ng_1n_SSH_l0gs!}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{4n_unusual_s1ght1ng_1n_SSH_l0gs!}"

def test_accept_single_word_training_flag(tmp_path: Path):
    # Regression: easy/training challenges do have single-word flags.
    # Make sure we don't overfit phase-4 by rejecting `picoCTF{welcome}`.
    (tmp_path / "flag.txt").write_text("picoCTF{welcome}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag == "picoCTF{welcome}"
```

- [ ] **Step 2: Run tests to confirm the reject tests fail**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_flag_extractor.py -v
```

Expected: the four new reject-tests FAIL; the three new accept-tests PASS; all prior tests still PASS.

- [ ] **Step 3: Extend `_looks_like_flag` in `hydra/flag_extractor.py`**

Replace the file contents with:

```python
import re
from pathlib import Path

_SPECIFIC = [
    re.compile(r"(?<![A-Za-z0-9_])flag\{[^}]+\}"),
    re.compile(r"(?<![A-Za-z0-9_])FLAG\{[^}]+\}"),
    re.compile(r"(?<![A-Za-z0-9_])CTF\{[^}]+\}"),
]
_GENERIC = re.compile(r"[A-Za-z0-9_]+\{[^}]+\}")
_FLAG_LINE = re.compile(r"FLAG:\s*(\S+)")

_MAX_BODY_LEN = 128

# Banned whole-body substrings, case-insensitive. A real flag body never
# contains these as part of an English word; leet substitutions (`fak3`,
# `pl4ceholder`) are fine and remain accepted.
_BANNED_BODY_SUBSTRINGS_CI = (
    "reminder",
    "http://",
    "https://",
    "```",
    "<|",
    "ignore previous",
    "fake",
    "placeholder",
    "fixme",
    "testing",
    "please_ignore",
    "pleaseignore",
    "your_flag_here",
    "sample",
    "redacted",
)


def extract_flag(*, flag_file: Path, stdout: str) -> str | None:
    # Priority 1: flag.txt
    if flag_file.exists():
        content = flag_file.read_text().strip()
        if content and _looks_like_flag(content):
            return content

    # Priority 2: last "FLAG: <value>" line
    line_matches = _FLAG_LINE.findall(stdout)
    if line_matches:
        candidate = line_matches[-1]
        if _looks_like_flag(candidate):
            return candidate

    # Priority 3: regex sweep — specific first, then generic, last *valid* match wins
    for pat in _SPECIFIC:
        hits = [h for h in pat.findall(stdout) if _looks_like_flag(h)]
        if hits:
            return hits[-1]
    hits = [h for h in _GENERIC.findall(stdout) if _looks_like_flag(h)]
    if hits:
        return hits[-1]
    return None


def _looks_like_flag(s: str) -> bool:
    m = _GENERIC.fullmatch(s)
    if not m:
        return False
    open_idx = s.index("{")
    body = s[open_idx + 1 : -1]
    if not body:
        return False
    if len(body) > _MAX_BODY_LEN:
        return False
    if any(ch.isspace() for ch in body):
        return False
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in body):
        return False
    body_lower = body.lower()
    for needle in _BANNED_BODY_SUBSTRINGS_CI:
        if needle in body_lower:
            return False
    # Reject all-dot bodies (format-spec echoes like `HTB{...}`).
    if body.strip(".") == "":
        return False
    return True
```

- [ ] **Step 4: Run tests to confirm all green**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_flag_extractor.py -v
```

- [ ] **Step 5: Commit**

```bash
cd <repo-root>
git add hydra/flag_extractor.py tests/unit/test_flag_extractor.py
git commit -m "fix(flag_extractor): reject placeholder bodies (phase-4 postmortem)"
```

---

## Task 2: Drop the generic regex sweep — require explicit derivation signal

The tighter body rules from Task 1 block the three specific phase-4 bodies, but the underlying issue is architectural: `extract_flag` scans all of stdout with a generic regex and accepts the last match. Any `PREFIX{...}` appearing anywhere — README, `strings` output, source code pasted via `cat`, comment — becomes a candidate flag. This is the vector that caught `bit{bit_idx}` (Python f-string source leaked via stdout).

Fix the class of bug: accept a flag only from `flag.txt` (the primary derivation signal) or a `FLAG: <value>` line in stdout (explicit agent echo). CLAUDE.md already mandates both, so no legitimate solve path disappears. We trade a small false-negative risk for eliminating a broad false-positive class.

**Files:**
- Modify: `hydra/flag_extractor.py`
- Modify: `tests/unit/test_flag_extractor.py`

- [ ] **Step 1: Add regression tests for the new architecture**

Append to `tests/unit/test_flag_extractor.py`:

```python
def test_regex_sweep_no_longer_accepts_bare_stdout(tmp_path: Path):
    # flag.txt empty, no `FLAG:` line — stdout contains HTB{...} only in
    # prose. Must return None (the phase-4 Blessed/Router-Web failure).
    (tmp_path / "flag.txt").write_text("")
    stdout = "Challenge README says: format is HTB{real_flag_here}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_regex_sweep_no_longer_accepts_fstring_leak(tmp_path: Path):
    # Python f-string source-code literal leaked via `cat script.py`.
    (tmp_path / "flag.txt").write_text("")
    stdout = "printing: bit{bit_idx} sample={s}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_regex_sweep_no_longer_accepts_binary_strings(tmp_path: Path):
    # `strings ./challenge/binary` leaked a hardcoded decoy into stdout.
    # Decoy contains digits so `fake` substring wouldn't catch it — only
    # the architectural "no sweep" fix saves us here.
    (tmp_path / "flag.txt").write_text("")
    stdout = "strings: HTB{n0_leak_f0r_y0u_1234567890abcdef}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_flag_line_still_works(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "working...\nFLAG: HTB{fr0m_l1ne_echo}\nbye"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{fr0m_l1ne_echo}"

def test_flag_file_still_works(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("HTB{fr0m_file}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="HTB{wrong}")
    assert flag == "HTB{fr0m_file}"

def test_empty_file_no_flag_line_returns_none(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag is None
```

- [ ] **Step 2: Delete tests that depend on the old generic-sweep behavior**

Open `tests/unit/test_flag_extractor.py` and **delete** these five tests (they assert the generic-sweep behavior we're removing):

```python
def test_regex_fallback(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "some output contains CTF{buried}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "CTF{buried}"
```

```python
def test_multiple_flags_take_most_specific_last(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "early CTF{first}\nlater flag{winner}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{winner}"
```

```python
def test_uppercase_flag(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG{SHOUTY}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "FLAG{SHOUTY}"
```

```python
def test_custom_prefix(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "the answer is picoCTF{pic0_flag}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "picoCTF{pic0_flag}"
```

```python
def test_nested_braces_ok(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "flag{inner}extra}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{inner}"
```

- [ ] **Step 3: Run tests — the new regression tests should fail until code is updated**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_flag_extractor.py -v
```

Expected: the three new "no longer accepts" tests FAIL (extractor still sweeps); others PASS.

- [ ] **Step 4: Remove the regex sweep from `extract_flag`**

Replace the `extract_flag` function body in `hydra/flag_extractor.py` with:

```python
def extract_flag(*, flag_file: Path, stdout: str) -> str | None:
    """Return a validated flag only if the agent produced a positive
    derivation signal — either `flag.txt` content or a `FLAG: <value>`
    echo in stdout.

    We deliberately do NOT sweep all of stdout with a generic
    `PREFIX{body}` regex: that accepts README format specs, decoy
    strings baked into challenge binaries by authors, and agent
    source-code f-string literals as flags. See phase-4 postmortem.
    """
    # Priority 1: flag.txt (the explicit derivation signal).
    if flag_file.exists():
        content = flag_file.read_text().strip()
        if content and _looks_like_flag(content):
            return content

    # Priority 2: the last `FLAG: <value>` line (explicit agent echo).
    for candidate in reversed(_FLAG_LINE.findall(stdout)):
        if _looks_like_flag(candidate):
            return candidate
    return None
```

Also delete the `_SPECIFIC` list at the top of the file (it's unused now). Keep `_GENERIC` (still used inside `_looks_like_flag`) and keep `_FLAG_LINE`.

- [ ] **Step 5: Run the whole suite, confirm green**

```
cd <repo-root> && .venv/bin/pytest -q
```

- [ ] **Step 6: Commit**

```bash
cd <repo-root>
git add hydra/flag_extractor.py tests/unit/test_flag_extractor.py
git commit -m "fix(flag_extractor): require explicit derivation signal; drop generic stdout sweep"
```

---

## Task 3: Dockerfile — install sigrok-cli and libsigrokdecode4

Phase-4 Debug spent 98 Bash calls trying to parse Saleae `.sal` binary format manually and was killed by OOM. `sigrok-cli` + `libsigrokdecode4` provide a real protocol decoder (UART/SPI/I2C/CAN/etc.). This is useful for any future hardware/signal-capture challenge, not only Debug.

**Files:**
- Modify: `docker/apt-packages.txt`

- [ ] **Step 1: Append the two packages**

Append these lines to `docker/apt-packages.txt`:

```
sigrok-cli
libsigrokdecode4
```

- [ ] **Step 2: Commit**

```bash
cd <repo-root>
git add docker/apt-packages.txt
git commit -m "feat(docker): install sigrok-cli + libsigrokdecode4 for UART/SPI/I2C decoding"
```

> Image rebuild is out of scope for this plan.

---

## Task 4: Dockerfile — ghidra-wrapper.sh enforcing a call-count cap

Router-Web phase-3 and phase-4 both died from over-decompiling: 17 functions across 5 Java scripts in phase-4, even with the specialist prose rule "max 2 functions". Prose rules are advisory; a shell wrapper that exits with a hard error after N calls binds. Applies to every future reverse-heavy challenge.

**Files:**
- Create: `docker/ghidra-wrapper.sh`
- Modify: `Dockerfile`

- [ ] **Step 1: Create the wrapper script**

Create `docker/ghidra-wrapper.sh`:

```sh
#!/bin/sh
# analyzeHeadless wrapper: cap Ghidra invocations per container so the
# agent cannot burn its token budget re-decompiling. Override with
# GHIDRA_MAX_CALLS=N if you legitimately need more passes. See
# phase-4 Router-Web postmortem.
set -eu

GHIDRA_REAL="/opt/ghidra_12.0.4_PUBLIC/support/analyzeHeadless"
STATE_FILE="${GHIDRA_STATE_FILE:-/tmp/.ghidra_call_count}"
MAX_CALLS="${GHIDRA_MAX_CALLS:-2}"

count=0
if [ -f "$STATE_FILE" ]; then
    count=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
fi

if [ "$count" -ge "$MAX_CALLS" ]; then
    cat >&2 <<EOF
error: analyzeHeadless call cap reached ($count/$MAX_CALLS).

Ghidra decompilation burns ~20K cache tokens per invocation and
rarely reveals more than: (a) reading the source if you have it, or
(b) curl-probing the live endpoint. You've already used $count pass(es).

Do this instead:
  - Web chal: fuzz the HTTP surface (curl every endpoint with junk,
    SQLi, path traversal, oversized payloads).
  - Pwn chal: write pwntools and send bytes to remote to confirm
    the vuln class before reversing more.
  - If more decompilation is genuinely justified, export
    GHIDRA_MAX_CALLS=N and document the reason in ./work/plan.md.

Exiting with code 2.
EOF
    exit 2
fi

count=$((count + 1))
echo "$count" > "$STATE_FILE"
exec "$GHIDRA_REAL" "$@"
```

- [ ] **Step 2: Mark it executable**

```
cd <repo-root> && chmod +x docker/ghidra-wrapper.sh
```

- [ ] **Step 3: Replace the analyzeHeadless symlink in the Dockerfile**

Open `Dockerfile`. Find this block near the Ghidra layer:

```dockerfile
 && curl -fsSL -o /tmp/ghidra.zip \
    "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_${GHIDRA_VERSION}_build/ghidra_${GHIDRA_VERSION}_PUBLIC_${GHIDRA_DATE}.zip" \
 && unzip -q /tmp/ghidra.zip -d /opt \
 && rm /tmp/ghidra.zip \
 && ln -s "/opt/ghidra_${GHIDRA_VERSION}_PUBLIC/support/analyzeHeadless" /usr/local/bin/analyzeHeadless
```

Remove only the last line (`&& ln -s ... analyzeHeadless`). Add this new block after the Ghidra layer:

```dockerfile
# analyzeHeadless wrapper: caps the number of Ghidra calls per
# container to prevent the agent from burning token budget on
# re-decompilation loops (see phase-4 Router-Web postmortem).
COPY docker/ghidra-wrapper.sh /usr/local/bin/analyzeHeadless
RUN chmod +x /usr/local/bin/analyzeHeadless
```

- [ ] **Step 4: Commit**

```bash
cd <repo-root>
git add docker/ghidra-wrapper.sh Dockerfile
git commit -m "feat(docker): cap analyzeHeadless invocations via shell wrapper"
```

---

## Task 5: Dockerfile — install sal2sigrok converter script

The Task 6 skill doc describes how to convert a `.sal` archive to sigrok input with a few numpy lines. Shipping an executable `sal2sigrok` means the agent types one command, not a seven-line numpy script. Generic to every future Saleae capture, not Debug-specific.

**Files:**
- Create: `docker/bin/sal2sigrok`
- Modify: `Dockerfile`

- [ ] **Step 1: Create the converter script**

Create `docker/bin/sal2sigrok`:

```python
#!/usr/bin/env python3
"""sal2sigrok — unpack a Saleae Logic 2 .sal capture into one-byte-per-sample
binary files, ready for `sigrok-cli --input-format binary`.

A .sal file is a zip archive containing meta.json + digital_N.bin
files, where each byte packs 8 consecutive samples of channel N
(LSB-first). This script extracts the zip, unpacks each channel
into a separate `<outdir>/channel_N.u8` file (one uint8 per sample,
0 or 1), and prints the suggested sigrok-cli invocation for UART
decoding.

Usage:
  sal2sigrok <input.sal> <outdir>

Example:
  sal2sigrok hw_debug.sal ./decoded
  for baud in 9600 19200 38400 57600 115200 230400 460800 921600; do
      echo "=== $baud ==="
      sigrok-cli --input-format binary:numchannels=1:samplerate=$(cat ./decoded/samplerate.txt) \\
                 --input-file ./decoded/channel_0.u8 \\
                 --protocol-decoders uart:baudrate=$baud:rx=0 \\
                 --protocol-decoder-annotations uart=rx-data 2>&1 | head -40
  done
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

try:
    import numpy as np
except ImportError:
    sys.stderr.write("error: numpy not installed. `pip install numpy`.\n")
    sys.exit(1)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        sys.stderr.write("usage: sal2sigrok <input.sal> <outdir>\n")
        return 2
    src = Path(argv[1])
    outdir = Path(argv[2])
    if not src.exists():
        sys.stderr.write(f"error: {src} does not exist\n")
        return 1
    outdir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src) as z:
        names = z.namelist()
        if "meta.json" not in names:
            sys.stderr.write(
                f"error: {src} is not a Saleae .sal archive (no meta.json)\n"
            )
            return 1
        meta = json.loads(z.read("meta.json"))
        z.extractall(outdir / "_raw")

    sample_rate = _resolve_sample_rate(meta)
    digital_files = sorted((outdir / "_raw").glob("digital_*.bin"))

    for dig in digital_files:
        idx = int(dig.stem.split("_")[1])
        raw = np.fromfile(dig, dtype=np.uint8)
        bits = np.unpackbits(raw, bitorder="little")
        out = outdir / f"channel_{idx}.u8"
        bits.astype(np.uint8).tofile(out)
        print(f"unpacked channel {idx}: {len(bits)} samples -> {out}")

    (outdir / "samplerate.txt").write_text(str(sample_rate) + "\n")
    print(f"sample rate: {sample_rate} Hz -> {outdir}/samplerate.txt")

    print()
    print("try decoding UART across common bauds:")
    print(
        "  for baud in 9600 19200 38400 57600 115200 230400 460800 921600; do\n"
        f"      echo === $baud ===\n"
        f"      sigrok-cli --input-format binary:numchannels=1:samplerate=$(cat {outdir}/samplerate.txt) \\\n"
        f"                 --input-file {outdir}/channel_0.u8 \\\n"
        "                 --protocol-decoders uart:baudrate=$baud:rx=0 \\\n"
        "                 --protocol-decoder-annotations uart=rx-data 2>&1 | head -40\n"
        "  done"
    )
    return 0


def _resolve_sample_rate(meta: dict) -> int:
    # Saleae meta.json has evolved; look in the expected places.
    for key in ("sample_rate", "samplerate", "sampleRate"):
        if key in meta:
            return int(meta[key])
    captures = meta.get("captures") or []
    if captures and isinstance(captures, list):
        c0 = captures[0]
        for key in ("sample_rate", "samplerate", "sampleRate"):
            if key in c0:
                return int(c0[key])
    # Last resort: assume a common Saleae rate.
    sys.stderr.write(
        "warning: sample_rate not found in meta.json; defaulting to 25_000_000 Hz\n"
    )
    return 25_000_000


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 2: Make it executable**

```
cd <repo-root> && chmod +x docker/bin/sal2sigrok
```

- [ ] **Step 3: Install it into the image**

Open `Dockerfile`. Just above the `WORKDIR /workspace` line at the bottom, add:

```dockerfile
# Custom helper binaries (sal2sigrok, etc.).
COPY docker/bin/ /usr/local/bin/hydra/
RUN ln -s /usr/local/bin/hydra/sal2sigrok /usr/local/bin/sal2sigrok
```

(The intermediate `/usr/local/bin/hydra/` directory keeps our helpers separate from system/apt binaries so they're discoverable as a group when debugging.)

- [ ] **Step 4: Commit**

```bash
cd <repo-root>
git add docker/bin/sal2sigrok Dockerfile
git commit -m "feat(docker): ship sal2sigrok converter for Saleae .sal captures"
```

---

## Task 6: UART/Saleae skill doc + forensics/misc-specialist references

Document the sigrok + sal2sigrok workflow and point the two specialists most likely to receive hardware-signal challenges at it. Generic recipe, reusable for any `.sal`/`.logicdata` capture.

**Files:**
- Create: `.claude/skills/hw/uart-sigrok.md` (new file; new directory)
- Modify: `.claude/agents/forensics-specialist.md`
- Modify: `.claude/agents/misc-specialist.md`

- [ ] **Step 1: Create the skill doc**

Create `.claude/skills/hw/uart-sigrok.md`:

```markdown
# Decoding UART / SPI / I2C from a Saleae .sal capture

When a challenge ships a `.sal` (Saleae Logic 2) capture — typically
UART boot logs for hardware challenges — use `sigrok-cli` with its
built-in protocol decoders. Manual binary parsing of the Saleae format
burns tokens fast and OOM-kills the container (see phase-3 and phase-4
Debug postmortems).

## The .sal format, briefly

A `.sal` is a zip archive:

```
meta.json          # sample_rate, channel layout, start/end timestamps
digital_0.bin      # packed uint8 bits of channel 0 (LSB-first)
digital_1.bin      # channel 1 if multi-channel
...
```

## The fast path (one-liner unpack + baud sweep)

`sal2sigrok` is pre-installed in the image. It unzips the archive,
unpacks each `digital_N.bin` into one-byte-per-sample, and prints the
sigrok-cli command to decode UART across common bauds.

```bash
sal2sigrok hw_debug.sal ./decoded
# The script's output includes a ready-to-paste loop. Run it:
for baud in 9600 19200 38400 57600 115200 230400 460800 921600; do
    echo "=== $baud ==="
    sigrok-cli --input-format binary:numchannels=1:samplerate=$(cat ./decoded/samplerate.txt) \
               --input-file ./decoded/channel_0.u8 \
               --protocol-decoders uart:baudrate=$baud:rx=0 \
               --protocol-decoder-annotations uart=rx-data 2>&1 | head -40
done | tee decoded.log

# Flag is usually in the boot banner. Grep it out:
grep -oE 'HTB\{[^}]+\}|flag\{[^}]+\}' decoded.log
```

The correct baud produces coherent ASCII (boot banners, `login:`,
`#`, kernel messages). Wrong bauds produce garbage bytes. Scan for
flag patterns in the decoded output.

## SPI / I2C variants

Same pipeline, different `--protocol-decoders`:

```bash
# SPI: clock on ch0, MOSI on ch1, MISO on ch2
sigrok-cli ... --protocol-decoders spi:clk=0:mosi=1:miso=2 \
               --protocol-decoder-annotations spi=mosi-data,spi=miso-data

# I2C: SCL on ch0, SDA on ch1
sigrok-cli ... --protocol-decoders i2c:scl=0:sda=1 \
               --protocol-decoder-annotations i2c=data
```

Multi-channel `.sal` files auto-unpack into `channel_0.u8`,
`channel_1.u8`, etc. Pass `binary:numchannels=N` and concatenate or
interleave the files as `sigrok-cli` expects.

## Token budget

- Unzip + meta.json + unpack: 1 tool call (`sal2sigrok <src> <out>`).
- Baud sweep across 8 rates: 1 tool call (the for-loop).
- Grep decoded output: 1 tool call.

Total: ~3 tool calls end-to-end. If you're on call 20 still manually
indexing bits in Python, stop and run `sal2sigrok`.
```

- [ ] **Step 2: Add a pointer from `forensics-specialist.md`**

Open `.claude/agents/forensics-specialist.md`. Append at the end:

```markdown

# Hardware / signal-capture skill

- `.claude/skills/hw/uart-sigrok.md` — decoding Saleae `.sal` UART/SPI/I2C
  captures with `sigrok-cli` + the pre-installed `sal2sigrok` helper.
  Use this any time you see `.sal`, `.logicdata`, or a challenge
  description mentioning "logic analyzer capture" or "serial signal".
```

- [ ] **Step 3: Add the same pointer from `misc-specialist.md`**

Open `.claude/agents/misc-specialist.md`. Append the same block (misc is the common fallback for hardware/ambiguous categories).

```markdown

# Hardware / signal-capture skill

- `.claude/skills/hw/uart-sigrok.md` — decoding Saleae `.sal` UART/SPI/I2C
  captures with `sigrok-cli` + the pre-installed `sal2sigrok` helper.
  Use this any time you see `.sal`, `.logicdata`, or a challenge
  description mentioning "logic analyzer capture" or "serial signal".
```

- [ ] **Step 4: Commit**

```bash
cd <repo-root>
git add .claude/skills/hw/uart-sigrok.md .claude/agents/forensics-specialist.md .claude/agents/misc-specialist.md
git commit -m "feat(skills): uart-sigrok hardware/signal decoding recipe"
```

---

## Task 7: Crypto HNP brute-force template + crypto-specialist reference

HNP (Hidden Number Problem) is a recurring class: top/bottom bits disclosed, recover the missing window. Applies far beyond Blessed — ECDSA nonce leaks, RSA partial-bit disclosures, LCG state recovery, EC point partial disclosures all fit the pattern. Ship a C+GMP brute-force with a Jacobi-symbol on-curve prefilter (~2300x faster than testing y), so any future HNP-class challenge has a starting point.

**Files:**
- Create: `exploits/crypto/ecc_hnp_search.c`
- Modify: `.claude/agents/crypto-specialist.md`

- [ ] **Step 1: Create the C template**

Create `exploits/crypto/ecc_hnp_search.c`:

```c
/*
 * ecc_hnp_search.c — HNP-class brute-forcer for EC challenges.
 *
 * When a challenge leaks the top N bits of an EC point x-coordinate
 * (via RNG, state disclosure, or partial ciphertext), enumerate the
 * unknown low W bits and test whether the candidate x lies on the
 * curve via the Jacobi symbol of (x^3 + a*x + b) mod p.
 *
 * Jacobi prefilter is ~2300x faster than computing a modular square
 * root. On modern x86_64 with GMP: ~60 ns/candidate. A full 2^32
 * window finishes in ~4 minutes. Applies to any HNP-class challenge
 * where the unknown fits into 2^32–2^40.
 *
 * Build:
 *   gcc -O3 -march=native ecc_hnp_search.c -o ecc_hnp_search -lgmp
 *
 * Edit the constants below to match the challenge curve and the
 * known high-bits pattern, then run. Hits print to stdout:
 *   HIT x = 0x<hex>  (guess=<low-bits>)
 *
 * After a hit, lift x back to a real point (compute y via modular
 * sqrt) and verify against the remote before trusting it — Jacobi
 * only tells you the RHS is a QR, not that you have the right point.
 */

#include <stdio.h>
#include <stdint.h>
#include <gmp.h>

/* ---- Challenge-specific: EDIT THESE BEFORE COMPILING ---- */

/* Curve: y^2 = x^3 + A*x + B mod P. Example placeholder = secp256r1. */
static const char *P_STR = "ffffffff00000001000000000000000000000000ffffffffffffffffffffffff";
static const char *A_STR = "ffffffff00000001000000000000000000000000fffffffffffffffffffffffc";
static const char *B_STR = "5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b";

/* Known high bits of x, left-shifted so the unknown occupies the
 * low WINDOW_BITS.  Replace with the actual disclosed prefix. */
static const char *X_HIGH_STR = "0000000000000000000000000000000000000000000000000000000100000000";
#define WINDOW_BITS 32

/* ---- End challenge-specific section ---- */

int main(void) {
    mpz_t p, a, b, x_high, x, rhs, lhs;
    mpz_inits(p, a, b, x_high, x, rhs, lhs, NULL);

    mpz_set_str(p, P_STR, 16);
    mpz_set_str(a, A_STR, 16);
    mpz_set_str(b, B_STR, 16);
    mpz_set_str(x_high, X_HIGH_STR, 16);

    uint64_t window = 1ULL << WINDOW_BITS;
    uint64_t hits = 0;
    uint64_t progress_step = window / 64;

    for (uint64_t guess = 0; guess < window; guess++) {
        if (progress_step && (guess % progress_step) == 0) {
            fprintf(stderr, "\rprogress: %lu / %lu", guess, window);
            fflush(stderr);
        }

        /* x = x_high | guess */
        mpz_set(x, x_high);
        mpz_add_ui(x, x, guess);

        /* rhs = x^3 + a*x + b mod p */
        mpz_mul(rhs, x, x);
        mpz_mul(rhs, rhs, x);
        mpz_mul(lhs, a, x);
        mpz_add(rhs, rhs, lhs);
        mpz_add(rhs, rhs, b);
        mpz_mod(rhs, rhs, p);

        int j = mpz_jacobi(rhs, p);
        if (j == 1) {
            gmp_printf("HIT x = 0x%Zx  (guess=%lu)\n", x, guess);
            hits++;
        }
    }

    fprintf(stderr, "\ndone, %lu hits in %lu candidates\n", hits, window);

    mpz_clears(p, a, b, x_high, x, rhs, lhs, NULL);
    return 0;
}
```

- [ ] **Step 2: Add a pointer from `crypto-specialist.md`**

Open `.claude/agents/crypto-specialist.md`. Append at the end (below any existing "Exploit templates reference" section):

```markdown

# HNP brute-force template

- `exploits/crypto/ecc_hnp_search.c` — C + GMP brute-forcer with Jacobi
  on-curve prefilter (~60 ns/candidate, so 2^32 scan completes in
  ~4 minutes). Applies whenever a challenge leaks top bits of an EC
  x-coordinate (Blessed-class); the same template pattern adapts to
  RSA partial-bit disclosures and ECDSA nonce leaks by replacing the
  on-curve check with the relevant congruence.
- See `.claude/skills/crypto/hnp-attacks.md` for the full HNP decision
  tree (when to brute, when to lattice, when to give up).
```

- [ ] **Step 3: Commit**

```bash
cd <repo-root>
git add exploits/crypto/ecc_hnp_search.c .claude/agents/crypto-specialist.md
git commit -m "feat(exploits): ecc_hnp_search.c HNP brute-force with Jacobi prefilter"
```

---

## Task 8: HNP attacks skill doc

A template without a skill-level decision tree leaves the agent guessing *when* to use brute force vs. lattice reduction vs. giving up. Ship a concise playbook covering HNP generally (not just Blessed's shape).

**Files:**
- Create: `.claude/skills/crypto/hnp-attacks.md`
- Modify: `.claude/agents/crypto-specialist.md` (already edited in Task 7 — this task just ensures the reference exists and points at the right file)

- [ ] **Step 1: Create the skill doc**

Create `.claude/skills/crypto/hnp-attacks.md`:

```markdown
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
```

- [ ] **Step 2: Verify `crypto-specialist.md` points at the new skill**

Open `.claude/agents/crypto-specialist.md`. Confirm the block added in Task 7 Step 2 mentions `.claude/skills/crypto/hnp-attacks.md`. (Task 7 pre-wrote the reference; Task 8 just creates the file it refers to.)

- [ ] **Step 3: Commit**

```bash
cd <repo-root>
git add .claude/skills/crypto/hnp-attacks.md
git commit -m "feat(skills): hnp-attacks playbook with brute/lattice decision tree"
```

---

## Task 9: Remote-contact detector — orchestrator-level suspect gate

Phase-3 Abyss and phase-4 Blessed both built elaborate exploit infrastructure (simulators, C brute-forcers, benchmark scripts) but never sent a single packet to the remote target. A flag that surfaces from such a run is suspicious by construction — it must have come from README prose, a hardcoded binary string, or a hallucination, not from the challenge's response. Detect the no-contact case and demote to `solved_uncertain` so downstream verification (manual or the verifier-specialist) can intervene.

Generic to every category with a `remote` endpoint: pwn, web, crypto-over-TCP, misc-over-TCP.

**Files:**
- Create: `hydra/remote_contact.py`
- Create: `tests/unit/test_remote_contact.py`
- Modify: `hydra/orchestrator.py`

- [ ] **Step 1: Write the detector tests**

Create `tests/unit/test_remote_contact.py`:

```python
import json
from pathlib import Path

from hydra.remote_contact import parse_remote, was_remote_contacted


def test_parse_remote_bare_host_port():
    assert parse_remote("154.57.164.82:32300") == ("154.57.164.82", 32300)


def test_parse_remote_http_url():
    assert parse_remote("http://154.57.164.73:31277") == ("154.57.164.73", 31277)


def test_parse_remote_http_url_with_path():
    assert parse_remote("http://154.57.164.73:31277/app") == ("154.57.164.73", 31277)


def test_parse_remote_hostname_only():
    assert parse_remote("example.com") == ("example.com", None)


def test_parse_remote_none_returns_none():
    assert parse_remote(None) == (None, None)


def _fake_log(tmp_path: Path, assistant_messages: list[dict]) -> Path:
    f = tmp_path / "claude.stdout.jsonl"
    with f.open("w") as fh:
        for msg in assistant_messages:
            fh.write(json.dumps(msg) + "\n")
    return f


def test_was_contacted_no_log_file(tmp_path: Path):
    # No log yet — default to trusting (don't demote on missing evidence).
    missing = tmp_path / "nope.jsonl"
    assert was_remote_contacted(missing, "154.57.164.82:32300") is True


def test_was_contacted_no_remote_returns_true(tmp_path: Path):
    log = _fake_log(tmp_path, [])
    assert was_remote_contacted(log, None) is True
    assert was_remote_contacted(log, "") is True


def test_was_contacted_host_in_bash(tmp_path: Path):
    log = _fake_log(tmp_path, [{
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "curl -sI http://154.57.164.82:32300/"},
        }]},
    }])
    assert was_remote_contacted(log, "154.57.164.82:32300") is True


def test_was_contacted_port_only_is_enough(tmp_path: Path):
    # Agent might use `$HOST` var and the port literal — still counts.
    log = _fake_log(tmp_path, [{
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "nc $HOST 32300"},
        }]},
    }])
    assert was_remote_contacted(log, "154.57.164.82:32300") is True


def test_not_contacted_empty_log(tmp_path: Path):
    log = _fake_log(tmp_path, [])
    assert was_remote_contacted(log, "154.57.164.82:32300") is False


def test_not_contacted_unrelated_bash(tmp_path: Path):
    log = _fake_log(tmp_path, [{
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "gcc -O3 solve.c -o solve"},
        }]},
    }])
    assert was_remote_contacted(log, "154.57.164.82:32300") is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_remote_contact.py -v
```

Expected: `ModuleNotFoundError: hydra.remote_contact`.

- [ ] **Step 3: Implement `hydra/remote_contact.py`**

Create `hydra/remote_contact.py`:

```python
"""Did the agent actually contact the challenge remote?

A flag extracted from a run where the agent never opened a socket
to `<host>:<port>` is suspect by construction — it must have come
from README prose, a hardcoded binary string, or a hallucination,
not from the challenge's response. Parse the stream-json log
looking for bash commands / tool_use inputs mentioning the remote
host or port, and report a verdict.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+\-.]*://", re.IGNORECASE)


def parse_remote(remote: str | None) -> tuple[str | None, int | None]:
    """Parse a challenge remote spec into (host, port).

    Accepts:
      - `host:port` (bare TCP): returns (host, port).
      - `http://host:port[/path]` (URL): returns (host, port).
      - `hostname` (no port): returns (hostname, None).
      - None / empty: returns (None, None).
    """
    if not remote:
        return None, None
    s = remote.strip()
    s = _URL_SCHEME_RE.sub("", s)
    s = s.split("/", 1)[0]
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return host, None
    return s, None


def was_remote_contacted(log_file: Path, remote: str | None) -> bool:
    """Return True if the run's log contains evidence that the agent
    addressed the given remote.

    Heuristic: scan every assistant tool_use `input` payload (JSON-
    stringified) for the host or port substring. Generous on purpose
    — we want a false-positive in the *contact* sense (trust the run)
    rather than demote every genuine solve.

    Returns True when:
      - `remote` is None or empty (nothing to check).
      - The log file does not exist yet (no evidence either way —
        default to trusting, consistent with the "generous" policy).
      - Any tool_use input mentions the host or the port (as string).
    """
    if not remote:
        return True
    host, port = parse_remote(remote)
    if host is None:
        return True
    if not log_file.exists():
        return True

    needles: list[str] = [host]
    if port is not None:
        needles.append(str(port))

    with log_file.open("r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "assistant":
                continue
            content = msg.get("message", {}).get("content") or []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                payload = json.dumps(block.get("input", {}), ensure_ascii=False)
                for needle in needles:
                    if needle in payload:
                        return True
    return False
```

- [ ] **Step 4: Run tests to confirm green**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_remote_contact.py -v
```

- [ ] **Step 5: Wire the detector into the orchestrator**

Open `hydra/orchestrator.py`. Find the status-decision block (currently around lines 111–121):

```python
flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

if wr.timed_out:
    status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
elif flag:
    status, reason = "solved", None
elif wr.exit_code != 0:
    status = "error"
    reason = (wr.stderr[-1024:] if wr.stderr else f"worker exited {wr.exit_code}")
else:
    status, reason = "failed", "no flag recovered from stdout or flag.txt"
```

Replace with:

```python
flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

if wr.timed_out:
    status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
elif flag:
    log_file = wd / "logs" / "claude.stdout.jsonl"
    if c.remote and not was_remote_contacted(log_file, c.remote):
        status = "solved_uncertain"
        reason = (
            f"flag extracted but no evidence agent contacted remote "
            f"{c.remote} — likely false positive from README/binary string"
        )
    else:
        status, reason = "solved", None
elif wr.exit_code != 0:
    status = "error"
    reason = (wr.stderr[-1024:] if wr.stderr else f"worker exited {wr.exit_code}")
else:
    status, reason = "failed", "no flag recovered from stdout or flag.txt"
```

Also add the import at the top of `orchestrator.py` alongside the other imports:

```python
from hydra.remote_contact import was_remote_contacted
```

- [ ] **Step 6: Run the full suite**

```
cd <repo-root> && .venv/bin/pytest -q
```

Expected: green. No orchestrator tests break because the new branch only fires when `c.remote` is set AND the log doesn't contain it — existing orchestrator tests either don't set `remote` or supply a log that does.

- [ ] **Step 7: Commit**

```bash
cd <repo-root>
git add hydra/remote_contact.py hydra/orchestrator.py tests/unit/test_remote_contact.py
git commit -m "feat(orchestrator): demote flag to solved_uncertain if agent never contacted remote"
```

---

## Task 10: Exit-137 demotion — OOM'd containers go to `solved_uncertain`

Phase-3 and phase-4 Debug both exited with code 137 (SIGKILL / OOM). An OOM'd run's final state is compromised: the agent may have been mid-computation with stale intermediate values in `flag.txt` or stdout, or the OOM may have killed the worker while it was about to write the real flag. Either way, the result deserves human verification.

Generic across categories — any worker that OOM's qualifies.

**Files:**
- Modify: `hydra/orchestrator.py`
- Modify: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Inspect the existing orchestrator test file**

```
cd <repo-root> && head -40 tests/unit/test_orchestrator.py
```

Note whatever helper exists for constructing a `WorkerResult` / running `_safe_one`. If unclear, the fastest path is to write a focused new test that instantiates `Orchestrator` + fakes `_attempt`. The next step assumes a helper `_build_orch(tmp_path)` exists — if it doesn't, adapt to the real fixtures.

- [ ] **Step 2: Add the failing test**

Append to `tests/unit/test_orchestrator.py`:

```python
def test_exit_137_with_flag_is_solved_uncertain(tmp_path, monkeypatch):
    """A SIGKILL (OOM) exit must demote an otherwise-solved run.

    Build a minimal orchestrator, stub `_attempt` to return a WorkerResult
    with exit_code=137 and a flag in stdout, then run `_safe_one` and
    assert the recorded Result has status="solved_uncertain".
    """
    from hydra.orchestrator import Orchestrator, OrchestratorConfig
    from hydra.docker_worker import WorkerResult
    from hydra.models import Challenge
    from hydra.results import ResultsWriter

    runs = tmp_path / "runs"
    runs.mkdir()
    writer = ResultsWriter(
        jsonl_path=tmp_path / "results.jsonl",
        flags_path=tmp_path / "flags.json",
        results_path=tmp_path / "results.json",
    )
    cfg = OrchestratorConfig(
        parallel=1,
        timeout_s=600.0,
        model="claude-opus-4-6",
        image="hydra-worker",
        runs_dir=runs,
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    import asyncio
    orch._sem = asyncio.Semaphore(1)

    wd = runs / "Foo"
    (wd / "logs").mkdir(parents=True, exist_ok=True)
    (wd / "flag.txt").write_text("HTB{plausible_but_from_an_oom_run}\n")

    stub_wr = WorkerResult(
        stdout="", stderr="", exit_code=137, timed_out=False, duration_s=10.0,
    )

    async def _fake_attempt(self, c, subpath):
        return wd, stub_wr
    monkeypatch.setattr(Orchestrator, "_attempt", _fake_attempt)

    c = Challenge(name="Foo", description="x", remote="example.com:1234")
    asyncio.run(orch._safe_one(c))

    assert len(orch._results) == 1
    r = orch._results[0]
    assert r.status == "solved_uncertain", f"expected solved_uncertain, got {r.status}"
    assert "OOM" in (r.reason or "") or "137" in (r.reason or "")
```

- [ ] **Step 3: Run to confirm it fails**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_orchestrator.py::test_exit_137_with_flag_is_solved_uncertain -v
```

Expected: current orchestrator treats exit 137 + flag as `solved` → test FAILS.

- [ ] **Step 4: Add the OOM demotion to orchestrator status logic**

In `hydra/orchestrator.py`, find the `elif flag:` branch you edited in Task 9 Step 5:

```python
elif flag:
    log_file = wd / "logs" / "claude.stdout.jsonl"
    if c.remote and not was_remote_contacted(log_file, c.remote):
        status = "solved_uncertain"
        reason = (
            f"flag extracted but no evidence agent contacted remote "
            f"{c.remote} — likely false positive from README/binary string"
        )
    else:
        status, reason = "solved", None
```

Replace with:

```python
elif flag:
    log_file = wd / "logs" / "claude.stdout.jsonl"
    if wr.exit_code == 137:
        status = "solved_uncertain"
        reason = (
            "worker exited 137 (SIGKILL / OOM) — flag may be stale, "
            "verify manually before submitting"
        )
    elif c.remote and not was_remote_contacted(log_file, c.remote):
        status = "solved_uncertain"
        reason = (
            f"flag extracted but no evidence agent contacted remote "
            f"{c.remote} — likely false positive from README/binary string"
        )
    else:
        status, reason = "solved", None
```

- [ ] **Step 5: Run the test**

```
cd <repo-root> && .venv/bin/pytest tests/unit/test_orchestrator.py -v
```

Expected: the new test PASSES. No previously-green test goes red.

- [ ] **Step 6: Run the full suite**

```
cd <repo-root> && .venv/bin/pytest -q
```

- [ ] **Step 7: Commit**

```bash
cd <repo-root>
git add hydra/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(orchestrator): demote OOM-killed (exit 137) solves to solved_uncertain"
```

---

## Done check

After all ten tasks:

```bash
cd <repo-root>
.venv/bin/pytest -q
git log --oneline -13
```

Expected: all tests green; **10 new commits** on `main` on top of the previous phase-3 fixes.

To pick up the Docker-side changes (Tasks 3, 4, 5) in the next run, rebuild:

```bash
cd <repo-root>
docker build -t hydra-worker .
```

(Out of scope for this plan.)
