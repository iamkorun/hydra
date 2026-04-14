# Hydra — CTF Solver Agent — Design Spec

**Date:** 2026-04-14
**Status:** Draft, awaiting user review
**Scope:** v1 batch solver (Level B — orchestrator + specialists + 8 core skills + 15 exploit templates)

---

## 1. Goal

A batch CTF solver. User hands in a JSON list of challenges; Hydra returns flags.
Optimized for **solve rate × speed** in live competitions. No platform integration —
flags are pasted into the CTF platform by the user.

**Primary use case:** Live CTF events (CTFd, rCTF, or other jeopardy-style platforms).
**Secondary:** running against benchmark suites (Cybench, NYU_CTF_Bench) for iteration.

## 2. Decisions matrix

| # | Decision | Choice |
|---|----------|--------|
| Q1 | Use case | Live comps (primary) + benchmarks |
| Q2 | Platform integration | None — JSON in, flags out |
| Q4 | JSON schema | Flexible — orchestrator sniffs field names |
| Q5 | Parallelism | Configurable, default 8 |
| Q6 | Model | Claude Opus 4.6 (1M context) |
| Q7 | Timeout | 60 min default, `--timeout` flag |
| Q8 | Isolation | Per-worker Docker container |
| Q9 | Output | Streaming JSONL + final JSON + terminal |
| Q10 | Resume | Auto from JSONL + `--retry-failed` + `--only` |
| Q11 | Input source | File path or stdin |
| Q12 | File delivery | Bind-mount `./runs/<name>/` into `/workspace` |
| Q13 | Base image | Custom `ubuntu:24.04` + full CTF toolchain |
| Q14 | Claude placement | Inside container (API key via `-e`) |
| Q16 | Orchestrator language | Python 3.12 + asyncio |
| Q17 | Prompt stack | CLAUDE.md + 6 specialists + 8 skills + 15 exploits (Level B) |
| Q18 | Orchestration shape | Single Python script, asyncio.Semaphore |

## 3. Architecture

```
                        HOST
 ┌──────────────────────────────────────────────────────────────┐
 │   challenges.json                                            │
 │        │                                                     │
 │        ▼                                                     │
 │   hydra solve ──► Orchestrator (hydra.py, asyncio)           │
 │                   │                                          │
 │                   ├─► normalize JSON (flexible schema)       │
 │                   ├─► create ./runs/<name>/ per challenge    │
 │                   ├─► asyncio.Semaphore(N)                   │
 │                   ├─► spawn docker workers (parallel)        │
 │                   │                                          │
 │                   ├─► stream results.jsonl                   │
 │                   ├─► update flags.json                      │
 │                   └─► write ./failures/<name>.md on fail     │
 │                                                              │
 │   ./runs/<name>/  ─┐   ./CLAUDE.md ─┐   ./.claude/ ─┐        │
 │   ./exploits/ ─┐   │                │               │        │
 └────────────────┼───┼────────────────┼───────────────┼────────┘
                  │   │                │               │
                  ▼   ▼                ▼               ▼
 ┌──────────────────────────────────────────────────────────────┐
 │  CONTAINER (hydra-worker image, one per challenge)           │
 │                                                              │
 │   /workspace/     ← bind-mount of ./runs/<name>/             │
 │     ├── challenge/  (input files, README.md, hints.md)       │
 │     ├── work/       (solver scratch)                         │
 │     ├── logs/       (claude stdout/stderr)                   │
 │     └── flag.txt    (final flag)                             │
 │                                                              │
 │   /workspace/CLAUDE.md   ← bind-mount (ro)                   │
 │   /workspace/.claude/    ← bind-mount (ro) — agents + skills │
 │   /workspace/exploits/   ← bind-mount (ro)                   │
 │                                                              │
 │   claude -p "..." --model claude-opus-4-6                    │
 │      ├─► triage agent reads CLAUDE.md                        │
 │      ├─► Task() → <category>-specialist                      │
 │      ├─► specialist reads .claude/skills/<cat>/<attack>.md   │
 │      ├─► specialist copies exploits/<cat>/<tpl>.py → work/   │
 │      ├─► adapts & runs → writes flag.txt + "FLAG: <flag>"    │
 │      └─► or writes work/postmortem.md if stuck               │
 │                                                              │
 │   Tools pre-baked in image:                                  │
 │   pwntools, r2, ghidra, sage, z3, angr, volatility3, ffuf,   │
 │   gobuster, sqlmap, nikto, exiftool, binwalk, tshark,        │
 │   RsaCtfTool, one_gadget, ROPgadget, upx, steghide, zsteg    │
 └──────────────────────────────────────────────────────────────┘
```

**Three-tier knowledge hierarchy:**

```
CLAUDE.md (thin)
   ↓
.claude/agents/<category>-specialist.md (role, process, references)
   ↓
.claude/skills/<category>/<attack>.md (detailed playbook — loaded on demand)
   ↓
exploits/<category>/<template>.py (working code — copy + adapt)
```

Each layer loads the next only when needed. Context stays focused.

## 4. Components

### 4.1 `hydra.py` — orchestrator

Single-file Python (~300 lines). Responsibilities:

- CLI parsing (`argparse`)
- Flexible JSON normalization
- Per-challenge workdir setup
- Async parallel dispatch via `asyncio.Semaphore(N)` + `asyncio.create_subprocess_exec`
- Docker invocation (`docker run`)
- Flag extraction
- Streaming JSONL + final JSON output
- Failure-log generation (`./failures/<name>.md`)
- SIGINT handling

### 4.2 `Dockerfile` — `hydra-worker` image

Base: `ubuntu:24.04`. Approximate final size: 4–5 GB.

Layered by change-frequency (bottom to top = least to most likely to churn):

```dockerfile
FROM ubuntu:24.04

# System essentials
RUN apt update && apt install -y \
    build-essential git curl wget jq xxd file \
    python3 python3-pip python3-venv \
    nodejs npm \
    ...

# Python CTF stack (pinned versions)
RUN pip install \
    pwntools==4.13.* \
    z3-solver==4.13.* \
    angr==9.2.* \
    pycryptodome==3.20.* \
    gmpy2==2.2.* \
    sympy==1.13.* \
    requests==2.32.* \
    beautifulsoup4==4.12.* \
    playwright==1.48.* \
    pyjwt==2.10.* \
    r2pipe==1.9.*

# Web tools
RUN apt install -y ffuf gobuster sqlmap nikto wfuzz

# Reverse tools
RUN apt install -y radare2 ltrace strace upx-ucl

# Crypto (sagemath is huge)
RUN apt install -y sagemath

# Forensics
RUN apt install -y binwalk foremost steghide \
    && pip install volatility3 \
    && apt install -y tshark exiftool zsteg

# External tools (git installs)
RUN git clone https://github.com/RsaCtfTool/RsaCtfTool /opt/RsaCtfTool \
    && pip install -r /opt/RsaCtfTool/requirements.txt
RUN gem install one_gadget
RUN pip install ROPgadget

# Claude CLI
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /workspace
```

### 4.3 `CLAUDE.md` — thin triage prompt

Target: ~100 lines. Replaces the current 8 KB file. Contents:

- Role: "You are the triage+dispatch agent for a CTF."
- Workflow: read challenge → classify → `Task()` to category specialist → verify flag.
- Flag format regexes.
- Pivot/stop rules (from current CLAUDE.md, trimmed).
- References all 6 specialists by name.

### 4.4 `.claude/agents/` — 6 specialist subagents

Each ~120 lines. Structure:

```markdown
---
name: <category>-specialist
description: Solve <category> CTF challenges.
---

# Role
<deep domain priming>

# Process
1. Examine artifacts
2. Identify attack class (checklist by signals)
3. If classic attack: read .claude/skills/<category>/<attack>.md
4. If template exists: cp exploits/<category>/<tpl>.py ./work/solve.py, adapt
5. Otherwise: write solver from scratch in ./work/solve.py
6. Run, iterate, extract flag
7. On stuck: write ./work/postmortem.md

# Skills reference
- .claude/skills/<category>/<attack-1>.md — <when to use>
- ...

# Exploit templates reference
- exploits/<category>/<template-1>.py — <when to use>
- ...
```

Six files: `pwn-specialist.md`, `crypto-specialist.md`, `web-specialist.md`,
`rev-specialist.md`, `forensics-specialist.md`, `misc-specialist.md`.

### 4.5 `.claude/skills/` — 8 core skills (P1)

The 8 highest-impact playbooks. Each 80–150 lines of concrete technique:

1. `crypto/rsa-attacks.md` — Wiener, Hastad, common modulus, Franklin-Reiter, Coppersmith, Fermat
2. `crypto/aes-modes.md` — ECB oracle, CBC bit-flip, CBC padding oracle, CTR nonce reuse
3. `pwn/rop-chains.md` — ROPgadget usage, stack pivot, ret2csu, ret2libc
4. `pwn/format-string.md` — `%n` writes, arbitrary read, GOT overwrite
5. `web/sqli-cheatsheet.md` — union, blind boolean, blind time, error-based
6. `web/ssti-bypass.md` — jinja2, twig, freemarker payloads + sandbox escapes
7. `web/jwt-attacks.md` — none alg, weak HMAC, kid injection, algorithm confusion
8. `forensics/stego-checklist.md` — full LSB/appended/metadata workflow

Non-goal: covering every technique. Covers the Pareto-dominant 80%.

### 4.6 `exploits/` — 15 high-impact templates (P1)

Battle-tested working scripts. Specialist copies → fills blanks → runs.

| # | Path | When to reach for it |
|---|------|----------------------|
| 1 | `crypto/rsa_wiener.py` | small d / large e |
| 2 | `crypto/rsa_hastad_small_e.py` | e=3, short m |
| 3 | `crypto/rsa_common_modulus.py` | same n, different e |
| 4 | `crypto/rsa_fermat.py` | close p and q |
| 5 | `crypto/lcg_predict.py` | LCG-based PRNG leaks |
| 6 | `crypto/xor_known_plaintext.py` | XOR with partial known-plaintext |
| 7 | `web/sqli_blind_time.py` | time-based blind SQLi |
| 8 | `web/ssti_jinja2.py` | jinja2 SSTI with sandbox escape |
| 9 | `web/jwt_none_alg.py` | JWT alg=none forging |
| 10 | `pwn/ret2libc.py` | classic ret2libc on x86_64 |
| 11 | `pwn/fmtstr_leak.py` | format string leak / GOT overwrite |
| 12 | `pwn/angr_find_input.py` | symbolic-exec "find input that reaches win" |
| 13 | `forensics/lsb_extract.py` | LSB steganography extractor |
| 14 | `forensics/volatility_profile.py` | memory dump triage |
| 15 | `forensics/pcap_extract_creds.py` | cred extraction from pcap |

Curated from public repos (RsaCtfTool, PayloadsAllTheThings, pwntools tutorials),
not written from scratch.

### 4.7 `tests/`

```
tests/
├── unit/
│   ├── test_normalize.py        # ~15 cases, various JSON schemas
│   ├── test_flag_extractor.py   # ~20 cases, various flag formats/placements
│   ├── test_workdir.py          # ~8 cases, correct layout
│   └── test_results.py          # JSONL + JSON serialization + resume logic
├── integration/
│   └── test_pipeline.py         # mocked docker, full orchestrator flow
└── fixtures/
    ├── challenges/              # sample JSON inputs
    └── stdout_samples/          # canned docker stdout for flag extractor
```

E2E (gated, opt-in `HYDRA_E2E=1`):

```
tests/e2e/
└── test_canned.py               # 5 trivial real challenges, Haiku model
```

## 5. Data flow

```
1. STARTUP
   $ hydra challenges.json [--parallel N] [--timeout S] [--retry-failed] [--only NAMES]

   - Parse args
   - Load challenges.json (file or stdin)
   - Check ANTHROPIC_API_KEY present
   - Check docker daemon reachable
   - If hydra-worker image missing: prompt, then `docker build .`
   - Pre-flight: require 10 GB free disk
   - If ./results.jsonl exists: load + dedup already-solved entries
     (unless --retry-failed or --only overrides)

2. NORMALIZATION
   For each raw challenge:
     canonical = {
       "name": sniff(name|title|id) || sha1(description)[:8],
       "description": sniff(description|prompt|task|challenge),
       "files": [Path(p) for p in sniff(files|attachments|paths)],
       "remote": sniff(remote|host|url|service),
       "hints": sniff(hints|hint),
       "category": sniff(category|tag),           # optional hint only
       "points": sniff(points|score|value),       # optional metadata
     }
   Reject: no description AND no files.

3. WORKDIR SETUP (fast, sequential)
   ./runs/<safe_name>/
     ├── challenge/
     │   ├── <files copied>
     │   ├── README.md       # built from canonical
     │   └── hints.md        # if hints present
     ├── work/
     ├── logs/
     └── flag.txt            # empty sentinel

   README.md template:
     # <name>
     **Category:** <category or "unknown">
     **Points:** <points or "?">
     **Remote:** <remote or "none">

     ## Description
     <description>

     ## Files
     - <filename>

4. PARALLEL DISPATCH
   sem = asyncio.Semaphore(parallel)
   await asyncio.gather(*[run(ch) for ch in challenges])

   async def run(ch):
     async with sem:
       result = await spawn_worker(ch)
     append_results_jsonl(result)
     update_flags_json(result)
     if result.status != "solved":
       write_failure_md(result)
     print_status_line(result)

5. WORKER INVOCATION (spawn_worker)
   docker run --rm \
     --name hydra-<name>-<uuid8> \
     --network bridge \
     --memory 8g --cpus 2 \
     -v $(pwd)/runs/<name>:/workspace \
     -v $(pwd)/CLAUDE.md:/workspace/CLAUDE.md:ro \
     -v $(pwd)/.claude:/workspace/.claude:ro \
     -v $(pwd)/exploits:/workspace/exploits:ro \
     -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
     -w /workspace \
     hydra-worker \
     claude -p "Solve the CTF challenge. Read CLAUDE.md. Triage, dispatch to specialist, recover flag." \
       --model claude-opus-4-6 \
       --dangerously-skip-permissions \
       --output-format stream-json

   - stdout → ./runs/<name>/logs/claude.stdout.jsonl
   - stderr → ./runs/<name>/logs/claude.stderr.log
   - await proc.wait() with asyncio.wait_for(timeout)

6. FLAG EXTRACTION (priority order)
   a. Read ./runs/<name>/flag.txt — if non-empty, validate against regexes
   b. Scan stdout for literal "FLAG: <value>" — last occurrence
   c. Regex sweep stdout with:
        flag\{[^}]+\}
        FLAG\{[^}]+\}
        CTF\{[^}]+\}
        [A-Za-z0-9_]+\{[^}]+\}           # generic (least specific, last-resort)
      Pick the most-specific match from the latest stdout segment.
   d. No flag → status = "failed"

7. RESULT PERSISTENCE
   ./results.jsonl (appended, fsync'd):
     {
       "name": "baby-rsa",
       "status": "solved",               # solved | failed | timeout | error
       "flag": "flag{w1ener_w1ns}",
       "duration_s": 47.3,
       "started_at": "2026-04-14T12:05:21Z",
       "finished_at": "2026-04-14T12:06:08Z",
       "worker_exit_code": 0,
       "reason": null,                   # filled on non-solved
       "work_dir": "./runs/baby-rsa/"
     }

   ./flags.json (rewritten atomically each update):
     {
       "baby-rsa": "flag{w1ener_w1ns}",
       ...
       "__failed__": ["pwn2", "web3"]
     }

   ./failures/<name>.md (written only if failed):
     # <name> — FAILED (<reason>)
     **Category:** ...
     **Description:** ...
     **Duration:** ...
     ## Why it failed
     <reason + context>
     ## Last 50 lines of transcript
     <stdout tail>
     ## Agent postmortem (if written)
     <contents of ./runs/<name>/work/postmortem.md>
     ## Reproduction
     Logs:        ./runs/<name>/logs/claude.stdout.jsonl
     Scratch:     ./runs/<name>/work/
     Input files: ./runs/<name>/challenge/

   ./failures/SUMMARY.md (rewritten on any failure):
     # N failures out of M
     | Challenge | Reason | Duration | Postmortem? |

   Terminal line:
     ✓ baby-rsa    → flag{w1ener_w1ns}     (47s)
     ✗ pwn2        → (timeout after 60m)

8. FINAL (all done or SIGINT)
   - Write ./results.json (final aggregate: summary stats + all entries from jsonl)
     {
       "run_id": "2026-04-14T12:03:00Z",
       "summary": {
         "total": 50, "solved": 42, "failed": 6, "timeout": 2,
         "solve_rate": 0.84, "total_duration_s": 4821
       },
       "challenges": [<entries from results.jsonl>]
     }
   - ./flags.json finalized (already up-to-date from per-challenge updates)
   - ./results.jsonl flushed
   - ./failures/SUMMARY.md finalized
   - Write summary block to terminal (solve rate, wall-clock, failure list)
   - Exit 0 if any flag recovered, 1 otherwise (non-fatal signal)
```

## 6. CLI surface

```
hydra <challenges.json>                # or `-` for stdin

  --parallel N             Concurrent workers (default: 8)
  --timeout SECONDS        Per-challenge wall-clock (default: 3600)
  --model MODEL            Claude model (default: claude-opus-4-6)
  --retry-failed           Re-run entries currently marked failed/timeout/error
  --only NAMES             Comma-separated list; only run these
  --runs-dir DIR           Where to put ./runs/ (default: ./runs)
  --results FILE           Path for results.json (default: ./results.json)
  --jsonl FILE             Path for streaming log (default: ./results.jsonl)
  --flags-out FILE         Path for flags.json (default: ./flags.json)
  --dry-run                Normalize + set up workdirs; skip workers
  --rebuild-image          Force `docker build` before running
```

No subcommands. One command. Sensible defaults.

## 7. Repository layout

```
hydra/
├── CLAUDE.md                        # thin triage+dispatch prompt
├── Dockerfile                       # hydra-worker image
├── pyproject.toml                   # deps + entry point
├── hydra.py                         # orchestrator (single file)
│
├── .claude/
│   ├── agents/                      # 6 specialists
│   │   ├── pwn-specialist.md
│   │   ├── crypto-specialist.md
│   │   ├── web-specialist.md
│   │   ├── rev-specialist.md
│   │   ├── forensics-specialist.md
│   │   └── misc-specialist.md
│   └── skills/                      # 8 core playbooks (P1)
│       ├── crypto/
│       │   ├── rsa-attacks.md
│       │   └── aes-modes.md
│       ├── pwn/
│       │   ├── rop-chains.md
│       │   └── format-string.md
│       ├── web/
│       │   ├── sqli-cheatsheet.md
│       │   ├── ssti-bypass.md
│       │   └── jwt-attacks.md
│       └── forensics/
│           └── stego-checklist.md
│
├── exploits/                        # 15 templates (P1)
│   ├── crypto/
│   │   ├── rsa_wiener.py
│   │   ├── rsa_hastad_small_e.py
│   │   ├── rsa_common_modulus.py
│   │   ├── rsa_fermat.py
│   │   ├── lcg_predict.py
│   │   └── xor_known_plaintext.py
│   ├── web/
│   │   ├── sqli_blind_time.py
│   │   ├── ssti_jinja2.py
│   │   └── jwt_none_alg.py
│   ├── pwn/
│   │   ├── ret2libc.py
│   │   ├── fmtstr_leak.py
│   │   └── angr_find_input.py
│   └── forensics/
│       ├── lsb_extract.py
│       ├── volatility_profile.py
│       └── pcap_extract_creds.py
│
├── tests/
│   ├── unit/
│   │   ├── test_normalize.py
│   │   ├── test_flag_extractor.py
│   │   ├── test_workdir.py
│   │   └── test_results.py
│   ├── integration/
│   │   └── test_pipeline.py
│   ├── e2e/
│   │   └── test_canned.py           # gated by HYDRA_E2E=1
│   └── fixtures/
│       ├── challenges/
│       └── stdout_samples/
│
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-04-14-hydra-ctf-agent-design.md   (this file)
```

## 8. Error handling

| Failure | Handling |
|---------|----------|
| Docker image missing | Prompt: "build now? (y/N)". On yes → `docker build`. Else exit. |
| `ANTHROPIC_API_KEY` missing | Fail fast with clear message. |
| Docker daemon unreachable | Fail fast; instruct user to start docker. |
| Out of disk (<10 GB) | Fail fast before spawning workers. |
| Invalid JSON overall | Fail fast. |
| Per-entry normalization fail | Skip entry; record `{status: "error", reason: "unparseable"}`; proceed with rest. |
| File path in JSON doesn't exist | Skip that file; log warning; proceed (description may still be solvable). |
| Worker wall-clock timeout | `asyncio.wait_for` → `docker stop --time 10`. Result `{status: "timeout"}`. |
| Worker exits non-zero | Capture last 1 KB of stderr into `reason`. `{status: "error"}`. |
| API rate limit | Claude CLI's own retry logic. Orchestrator continues. |
| Multiple flags in stdout | Use last occurrence matching most-specific regex. Log ambiguity. |
| Flag.txt malformed | Still save; mark `{status: "solved_uncertain", flag: <raw>}`. |
| SIGINT (Ctrl-C) | Catch, `docker stop` all running containers, wait ≤15 s, flush results.jsonl + results.json (partial) + flags.json + failures/, exit 130. |
| Memory pressure | Per-container `--memory 8g`; refuse to spawn if free RAM < `parallel × 8 GB`. |
| Malicious pwn binary | Contained inside Docker (seccomp default profile). Host not affected. |

## 9. Testing

### Unit (pytest, no docker)

- `test_normalize.py` — 15 cases across common JSON shapes (minimal, rich, unusual names, missing optional fields, unicode names, nested).
- `test_flag_extractor.py` — 20 cases: clean `flag{}`, uppercase, custom prefixes, multiple flags in one stdout, no flag, flag only in file, flag in stderr only, malformed.
- `test_workdir.py` — 8 cases: layout correctness, filename collisions, unicode paths, read-only sources.
- `test_results.py` — 5 cases: JSONL append atomicity, flags.json atomic rewrite, resume dedup, failure-md generation, SUMMARY.md aggregation.

### Integration (fake docker)

- Replace `docker` on `PATH` with a Python fake that reads a scenario file and emits canned stdout/exit codes.
- 10 scenarios: happy-path solve, flag in stdout only, flag in flag.txt only, timeout, worker crash, mixed batch, SIGINT during run, resume correctness, `--only` filter, `--retry-failed`.

### E2E (real docker, gated by `HYDRA_E2E=1`)

- 5 trivial canned challenges in `tests/e2e/fixtures/`:
  1. `base64_flag` — file contains base64-encoded flag
  2. `strings_flag` — flag visible via `strings binary`
  3. `rot13_flag` — description is rot13 of the flag
  4. `xor_key` — XORed flag + given key
  5. `tiny_rsa` — factorable small-modulus RSA (< 100 bits)
- Run with `--model claude-haiku-4-5` to cap cost at ~$0.10/run.
- Target: 5/5 pass. Regression detector for prompt/skill changes.

### Manual pre-comp smoke

Informal — run the E2E suite with Opus before a real comp to confirm everything works end-to-end. No dedicated script beyond `HYDRA_E2E=1 pytest tests/e2e --model opus`.

## 10. Phased build

### P1 — Ship-ready skeleton (est. 1.5 days)

Deliverables:
- `Dockerfile` (full CTF toolchain)
- `hydra.py` (orchestrator)
- `CLAUDE.md` (thin triage+dispatch, replaces current)
- 6 specialist agent files in `.claude/agents/`
- 8 core skill files in `.claude/skills/`
- 15 exploit templates in `exploits/` (curated from public repos)
- Unit + integration tests
- `pyproject.toml`
- `README.md` (user quickstart)

Acceptance: `hydra tests/fixtures/challenges/base64.json` recovers the flag.

### P2 — Hardening + E2E (est. 0.5 days)

Deliverables:
- E2E test suite with 5 canned challenges
- Ctrl-C cleanup verified
- Resume behavior verified
- Failure-log generation verified
- `HYDRA_E2E=1 pytest` passes 5/5 with Haiku

Acceptance: running a 20-challenge JSON from a past picoCTF hits ≥60% solve rate.

## 11. Out of scope (deferred)

- CTFd / rCTF / any platform integration (user pastes flags manually)
- Benchmark harness (Cybench, NYU_CTF_Bench — ad-hoc only via E2E-style runs)
- 17 additional skill files (beyond the 8 core) — add after first real comp reveals gaps
- 35 additional exploit templates (beyond the 15) — same criterion
- Persistent learning DB (`notes/lessons-learned.md`)
- Tiered model selection (Haiku-for-easy / Opus-for-hard auto-routing)
- Multi-host distribution / task queue (Redis, Celery)
- Subscription-based auth (API key only for now)
- `hydra status` / `hydra clean` / `hydra smoke` auxiliary commands — not needed; a
  `rm -rf runs results.* failures/ flags.json` covers clean.
- Cost/token tracking as a user-facing feature (still recorded in results.jsonl for
  debugging, just not summarized in terminal output)

## 12. Success criteria

- **Functional:** from a valid `challenges.json`, produces a `flags.json` with at
  least one correct flag and per-challenge detail in `results.jsonl`.
- **Resilient:** survives SIGINT, worker timeouts, worker crashes, missing files;
  always produces usable partial output.
- **Performant:** a 50-challenge batch at `--parallel 8` completes in wall-clock ≤
  1.5 × the longest single solve (i.e., parallelism delivers near-linear speedup
  up to the semaphore cap).
- **Debuggable:** every failure has a self-contained `./failures/<name>.md` with
  enough information to either manually solve the challenge or fix the agent.

## 13. Open questions

None. All architecture decisions locked.

---

*End of design spec.*
