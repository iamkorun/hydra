# Hydra

[![CI](https://github.com/iamkorun/hydra/actions/workflows/ci.yml/badge.svg)](https://github.com/iamkorun/hydra/actions/workflows/ci.yml) ![license](https://img.shields.io/badge/license-MIT-blue) ![python](https://img.shields.io/badge/python-3.12%2B-blue) ![runtime](https://img.shields.io/badge/runtime-Claude%20Code-orange) ![supervision](https://img.shields.io/badge/supervision-3--layer-brightgreen)

**Autonomous CTF batch solver.** JSON in, flags out.

```
hydra challenges.json
# ✓ baby-rsa    → flag{w1ener_w1ns}  (47s)
# ✓ login       → flag{sqli_r0ck5}   (2m13s)
# ✗ pwn2        → (timeout after 60m)
#
# solved 42/50 in 48m21s → ./flags.json
```
*(flags above are illustrative)*

**Built for** CTF players who want to clear a category overnight,
researchers benchmarking agent capability across pwn/crypto/web/rev/forensics/misc,
and tool builders studying how to keep long-running LLM agents on-track.

Each challenge runs in its own Docker container with Claude Code inside.
A triage agent ([`CLAUDE.md`](CLAUDE.md)) classifies the category and dispatches
to one of **7 specialist subagents** ([`.claude/agents/`](.claude/agents/)),
which pull from **~30 attack-pattern playbooks**
([`.claude/skills/`](.claude/skills/) — RSA / ECC / padding-oracle / LFI-to-RCE /
prototype-pollution / volatility / anti-debug / …). Hydra harvests and
aggregates across the whole batch — with live log streaming, automatic resume,
and pass@k parallel attempts.

**Three supervision layers** keep the agent honest:

1. **Operator babysit** — a separate Claude session running the
   [`prompts/hydra-babysit.md`](prompts/hydra-babysit.md) playbook
   monitors the batch every 270s and acts on a decision matrix
   (CONTINUE / KILL / UPGRADE / PAUSE).
2. **Deterministic watchdog** — a sidecar per worker that catches
   loop / OOM / cost-cap / idle failures without an LLM call.
3. **Pre-commit flag gate** — `hydra/flag_gate.py` vetoes
   malformed or provenance-light candidates before they reach
   `flags.json`.

## Architecture

```
                    ┌── L1: operator babysit (separate Claude session)
                    │       ScheduleWakeup 270s → jq logs → decision matrix
                    │       codified in prompts/hydra-babysit.md
                    │
challenges.json     │
       │            ▼
       ▼      [hydra batch — running, monitored]
┌─────────────┐
│ orchestrator│ ── spawns N workers (--parallel)
└──────┬──────┘
       │
       ▼
┌──────────────────────────┐
│ Docker container         │     ◀── L2: watchdog sidecar
│                          │           (loop / OOM / cost / idle — 0 token)
│  Claude Code (triage)    │
│      └─ specialist agent │
│         └─ flag.txt      │
└──────────┬───────────────┘
           │
           ▼
   flag_extractor ──▶ L3: flag_gate ──▶ flags.json + results.json
                       (deterministic, 0 token)
```

See [Supervision](#supervision) for the matrix + signals.

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

Try the toy challenges first — they exercise the full pipeline (orchestrator
+ watchdog + flag gate) in ~45 seconds and don't need a real CTF target:

```bash
hydra examples/challenges-toy.json
```

See [`examples/quickstart.md`](examples/quickstart.md) for a 5-minute walkthrough.

For real CTF batches:

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

## Supervision

Hydra's failure modes split cleanly in two: **mechanical** (looping,
OOM, runaway cost, malformed output) and **semantic** (wrong direction,
hallucinated facts, scope drift, partial flags). The supervision stack
is designed around that split.

- **Mechanical failures** are caught by deterministic code — the
  watchdog sidecar and the flag gate, both 0-token, both shipped in
  this repo as Python.
- **Semantic failures** are caught by a separate Claude session
  running a codified operator playbook. The playbook lives in
  [`prompts/hydra-babysit.md`](prompts/hydra-babysit.md) as a
  versioned prompt — not as Python code — so it stays forkable and
  domain-portable. A second playbook,
  [`prompts/bb-babysit.md`](prompts/bb-babysit.md), applies the same
  pattern to bug-bounty workflows.

### Layer 1 — Operator babysit (LLM supervisor)

A separate Claude Code session, primed with `prompts/hydra-babysit.md`,
runs alongside the batch. The playbook gives it:

- **Pre-flight gates** — verify the target's protocol handshake (not
  just port-open) before launching a worker. Defends against IP
  recycling on platforms that reuse boxes.
- **Cheap-check loop** — `ScheduleWakeup` every 180–270s (prompt-cache
  warm), then `jq`/`tail`/`stat` on the worker's jsonl to grade
  progress without reading the full transcript.
- **Decision matrix** — first-matching-row dispatch over
  CONTINUE / KILL / UPGRADE (sonnet → opus) / PAUSE on signals like
  *partial flag*, *target down*, *training-memory shortcut*,
  *cost over cap*, *solver spam*.
- **Scrub-before-commit** — if a partial / wrong flag was already
  recorded, the supervisor scrubs `flags.json` + downgrades
  `results.jsonl` so `--retry-failed` can re-pick the challenge.

To use it: paste the playbook into a Claude Code session, tell it the
challenges JSON + target IPs, and let it run. The worker is `hydra`
itself; the supervisor never invokes the model directly.

### Layer 2 — Watchdog (sidecar)

Runs alongside each worker container and tails
`runs/<name>/logs/claude.stdout.jsonl` for bad-behavior signals. Kills
the container before it blows its budget. Signals:

| Code | Trigger | CLI flag |
|---|---|---|
| `bash_repeat` | Same Bash command prefix fires N+ times | `--watchdog-max-bash-repeats` (default 3) |
| `solver_spam` | >N files written matching `work/{solve,probe,exploit}NNN.py` | `--watchdog-max-solver-variants` (default 5) |
| `cost_cap` | Estimated token cost exceeds cap | `--watchdog-cost-cap` (default $10) |
| `oom_preempt` | Container RSS ≥ X% of memory limit | `--watchdog-mem-kill-pct` (default 90%) |
| `idle_work` | `work/` unchanged N sec while agent still tool-using | `--watchdog-idle-work-timeout` (default 180s) |

Disable with `--no-watchdog` (for debugging the agent itself).

Killed runs land in `results.jsonl` as `status: failed` with
`reason: watchdog: <code> (<detail>)` — grep-friendly, and
`--retry-failed` re-picks them.


### Layer 3 — Flag gate (pre-commit)

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
{"name": "splash", "flag_prefix": "EXAMPLE",
 "expected_format": "EXAMPLE\\{[0-9a-f]{32}\\}"}
```

## What Hydra is not

To be straight about scope:

- **Not a CTF curriculum or learning tool.** It solves; it doesn't
  teach. If you want to learn pwn, read the writeups in
  [`notes/lessons-learned.md`](notes/lessons-learned.md) or the
  skill playbooks under [`.claude/skills/`](.claude/skills/) — but
  Hydra itself optimizes for *flag-out*, not *human-understands*.
- **Not SOTA on the hardest challenges.** pass@k helps on flaky
  ones, but the worker LLM is still the ceiling. Hard pwn / custom
  crypto / multi-stage chains still benefit from a skilled human.
- **Not cheap.** Per-challenge cost on `claude-opus-4-7` typically
  lands in the $0.50 – $4 range depending on category and timeout.
  The watchdog `cost_cap` defaults to $10/challenge — tune it.
- **Not zero-config.** You assemble `challenges.json` yourself.
  Hydra sniffs field names liberally, but it doesn't scrape CTF
  platforms for you.
- **Not affiliated with Anthropic.** Hydra uses Claude Code as the
  worker runtime, but is a third-party project.
- **Not a fleet hunter for bug bounty.** The
  [`prompts/bb-babysit.md`](prompts/bb-babysit.md) playbook is
  deliberately single-worker, supervised, scope-gated — because
  unsupervised fleets get programs banned.

## Development

```bash
.venv/bin/pytest
.venv/bin/python -m ruff check  # lint (E + F + B + UP rulesets)
```

## Roadmap

See [`ROADMAP.md`](ROADMAP.md). Headline items for v0.2: benchmark
on InterCode-CTF, `hydra supervise` subcommand, per-category cost
telemetry, and a "Hydra on Haiku" cheaper-supervisor variant.

## License & contributing

MIT — see [LICENSE](LICENSE). Read [`CONTRIBUTING.md`](CONTRIBUTING.md)
before opening a PR; it lists what merges easily, what requires
discussion, and what's out of scope. Issues and discussions live at:

- 🐛 [Issues](https://github.com/iamkorun/hydra/issues) — bugs, features
- 💬 [Discussions](https://github.com/iamkorun/hydra/discussions) — design questions, war stories, playbook forks

If you fork the supervision playbook for a different domain
(red-team engagement, kaggle-style ML competition, scraping pipeline,
etc.), please [open a playbook-fork issue](https://github.com/iamkorun/hydra/issues/new?template=playbook_fork.md)
— the [`prompts/`](prompts/) directory is meant to collect these.
