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
| `--parallel N` | `8` | Concurrent workers |
| `--timeout S` | `3600` | Per-challenge wall-clock (seconds) |
| `--model NAME` | `claude-opus-4-6` | Claude model |
| `--attempts K` | `1` | pass@k — K parallel attempts per challenge, first flag wins |
| `--retry-failed` | off | Re-run entries marked failed / timeout / error |
| `--only A,B,C` | — | Comma-separated names to run (skip others) |
| `--runs-dir PATH` | `./runs` | Per-challenge artifact dir |
| `--results PATH` | `./results.json` | Aggregate output |
| `--jsonl PATH` | `./results.jsonl` | Streamed one-line-per-challenge |
| `--flags-out PATH` | `./flags.json` | Flags-only output |
| `--credentials-dir PATH` | `~/.claude` | Host dir mounted at `/root/.claude:ro` |
| `--use-api-key` | off | Force API-key mode even if subscription is found |
| `--dry-run` | off | Normalize + prepare workdirs, don't run |
| `--rebuild-image` | off | `docker build` before running |

Run `hydra --help` for the canonical list.

## Output files

| File | Contents |
|---|---|
| `flags.json` | `{"name": "flag", ..., "__failed__": [names]}` — ready for platform upload |
| `results.json` | Final aggregate with per-challenge status and summary stats |
| `results.jsonl` | One line per finished challenge, appended live |
| `runs/<name>/` | Input files, agent scratch, full transcript logs |
| `runs/<name>/logs/claude.stdout.jsonl` | Full agent transcript, streamed live (`tail -f` works) |
| `failures/<name>.md` | Postmortem + last 50 log lines per unsolved challenge |
| `failures/SUMMARY.md` | Index of all failures with a reason column |

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

## Development

```bash
.venv/bin/pytest                # 99 tests
.venv/bin/python -m ruff check  # lint (E + F + B + UP rulesets)
```

## Architecture

See [`docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md`](docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md).
