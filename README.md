# Hydra

**Autonomous CTF batch solver.** JSON in, flags out.

```
hydra challenges.json
# ✓ baby-rsa    → flag{w1ener_w1ns}  (47s)
# ✓ login       → flag{sqli_r0ck5}   (2m13s)
# ✗ pwn2        → (timeout after 60m)
#
# solved 42/50 in 48m21s → ./flags.json
```

Each challenge runs in its own Docker container with Claude Code inside.
Claude triages the category (pwn / crypto / web / rev / forensics / misc),
dispatches to a specialist subagent, and writes the flag. Hydra harvests
and aggregates across the whole batch — with live log streaming, automatic
resume, and pass@k parallel attempts.

## Prerequisites

- Python 3.12+
- Docker CE (or Podman — set `HYDRA_CONTAINER_ENGINE=podman`)
- Claude Code auth: a logged-in `~/.claude/` (preferred) or `ANTHROPIC_API_KEY`

## Install

```bash
git clone https://github.com/iamkorun/hydra.git
cd hydra
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker build -t hydra-worker .        # 10–20 min on first build
```

## Quick start

```bash
# 1. Create challenges.json (see Input format below).
# 2. Solve:
hydra challenges.json

# Output lands in:
#   ./flags.json         — flags only, ready for CTF-platform upload
#   ./results.json       — full results with summary stats
#   ./runs/<name>/       — per-challenge artifacts (input, scratch, logs)
#   ./failures/<name>.md — postmortem for each unsolved challenge
```

## Authentication

Hydra auto-detects auth. Subscription is preferred.

| Method | Setup |
|---|---|
| Claude Max / Pro subscription | Run `claude` once on the host to log in. Hydra bind-mounts `~/.claude` into each container as read-only. |
| Anthropic API key | `export ANTHROPIC_API_KEY=sk-ant-...`. Used as fallback, or forced via `--use-api-key`. |

Override the auto-detected credential dir with `--credentials-dir /path/to/.claude`.

## Input format

Top-level is a JSON array. Hydra sniffs field names — each entry needs:

- A **name** field (`name`, `title`, or `id`) — auto-generated from a content hash if absent
- At least one of **description / task / prompt** or **files / attachments / paths**

Optional: `category`, `points`, `hints`, `remote`.

```json
[
  {"name": "baby-rsa", "description": "Decrypt this.", "files": ["/path/chal.py"]},
  {"name": "login",    "description": "http://ctf.example.com:8080"},
  {"name": "pwn1", "category": "pwn", "points": 200, "description": "ret2libc",
   "files": ["/tmp/pwn1"], "remote": "nc chal.example.com 1337"}
]
```

## CLI reference

| Flag | Default | Description |
|---|---|---|
| `--parallel N` | challenge count | Concurrent workers — defaults to the number of challenges in the input JSON |
| `--timeout S` | `3600` | Per-challenge wall-clock (seconds) |
| `--model NAME` | `claude-opus-4-7` | Claude model |
| `--attempts K` | `1` | pass@k — K parallel attempts per challenge, first flag wins |
| `--retry-failed` | off | Re-run entries marked failed / timeout / error |
| `--only A,B,C` | — | Comma-separated names to run (skip others) |
| `--runs-dir PATH` | `./<json-stem>/runs` | Per-challenge artifact dir |
| `--results PATH` | `./<json-stem>/results.json` | Aggregate output |
| `--jsonl PATH` | `./<json-stem>/results.jsonl` | Streamed one-line-per-challenge |
| `--flags-out PATH` | `./<json-stem>/flags.json` | Flags-only output |
| `--credentials-dir PATH` | `~/.claude` | Host dir mounted at `/root/.claude:ro` |
| `--use-api-key` | off | Force API-key mode even if subscription is found |
| `--dry-run` | off | Normalize + prepare workdirs, don't run |
| `--rebuild-image` | off | `docker build` before running |

Run `hydra --help` for the canonical list.

## Output files

All outputs default to `./<json-stem>/` (e.g. `hydra phase-1.json` writes
into `./phase-1/`). Stdin (`-`) falls back to cwd. Any explicit
`--runs-dir` / `--results` / `--jsonl` / `--flags-out` overrides win.

| File | Contents |
|---|---|
| `<json-stem>/flags.json` | `{"name": "flag", ..., "__failed__": [names]}` — ready for platform upload |
| `<json-stem>/results.json` | Final aggregate with per-challenge status and summary stats |
| `<json-stem>/results.jsonl` | One line per finished challenge, appended live |
| `<json-stem>/runs/<name>/` | Input files, agent scratch, full transcript logs |
| `<json-stem>/runs/<name>/logs/claude.stdout.jsonl` | Full agent transcript, streamed live (`tail -f` works) |
| `<json-stem>/failures/<name>.md` | Postmortem + last 50 log lines per unsolved challenge |
| `<json-stem>/failures/SUMMARY.md` | Index of all failures with a reason column |

## Resume

Re-running with the same output files is idempotent:

- Entries with `status == "solved"` are skipped automatically.
- Failures (`failed` / `timeout` / `error`) are also skipped by default so a
  long batch doesn't re-burn budget on hopeless challenges.

Retry failures explicitly:

```bash
hydra challenges.json --retry-failed
```

Delete `results.jsonl` to start fresh.

## pass@k (parallel attempts)

Run K attempts per challenge — first flag wins, siblings are cancelled:

```bash
hydra challenges.json --attempts 3 --parallel 8
```

Each attempt consumes a `--parallel` slot, so K=3 reduces effective
cross-challenge concurrency by 3×. In exchange, solve rate climbs on
flaky challenges — Palisade (arxiv 2412.02776) reports 83% → 95% on
InterCode-CTF moving from k=1 to k=10.

## Debugging a failure

```bash
cat failures/SUMMARY.md                     # index of all failures
cat failures/<name>.md                      # postmortem + log tail
less runs/<name>/logs/claude.stdout.jsonl   # full agent transcript
ls   runs/<name>/work/                      # solver scratch files
```

Logs stream to disk as the agent runs, so
`tail -f runs/<name>/logs/claude.stdout.jsonl` works live during a batch.

## Exploit discipline

Hydra enforces "derive, don't recall" at the prompt layer — a CTF solve must be
produced by running code against the target, not imported from training memory:

- **`.claude/skills/meta/exploit-debug.md`** — when a payload doesn't fire, the
  specialist runs a 6-step diagnostic ladder (reachable → payload arrives →
  endpoint live → response diff → oracle sanity → public-PoC diff) *before*
  iterating. Cuts the "write v1 → no response → write v2 that's basically v1"
  context burn we saw on time-based SQLi challenges.
- **`.claude/skills/meta/no-prior-knowledge.md`** — if a specialist falls back
  to training memory ("I know this room's creds are `mitch:secret`") it must
  audit-log to `./work/prior-knowledge.log` with derivation-attempt + risk.
  The `verifier-specialist` auto-`SUSPECT`s any candidate whose run emitted
  that log, so the triage agent re-dispatches with "derive the skipped step".
  Skipping the log = fabrication; verifier catches it on provenance.

Why it matters: without this, a specialist can score on a canonical challenge by
recalling the answer instead of exploiting it, and collapse on any variant. The
log turns silent shortcuts into an auditable signal.

## Safety rails

Hydra ships two deterministic supervision layers. Both run per-worker,
use zero tokens, and can be tuned via CLI flags.

<!-- Watchdog subsection added in a later wave -->

### Flag gate (pre-commit)

Every flag candidate runs through `hydra/flag_gate.py` before being
written to `flags.json`:

- REJECT: unclosed brace, wrong prefix, format mismatch, length bounds,
  control chars, whitespace. `flags.json` stays clean; status = `failed`.
- WARN: missing scratch artifacts, or `prior-knowledge.log` present.
  Status = `solved_uncertain`; flag is recorded but flagged for human
  verification.
- ACCEPT: normal.

Tighten the gate per-challenge in your JSON:
```
{"name": "splash", "flag_prefix": "WANLAI",
 "expected_format": "WANLAI\\{[0-9a-f]{32}\\}"}
```

## Development

```bash
.venv/bin/pytest                # 131 tests
.venv/bin/python -m ruff check  # lint (E + F + B + UP rulesets)
```

## Architecture

See [`docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md`](docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md).
