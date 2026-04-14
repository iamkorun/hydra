# Hydra

Autonomous CTF batch solver. JSON in, flags out.

```bash
hydra challenges.json
# ✓ baby-rsa    → flag{w1ener_w1ns}  (47s)
# ✓ login       → flag{sqli_r0ck5}   (2m13s)
# ✗ pwn2        → (timeout after 60m)
#
# solved 42/50 in 48m21s → ./flags.json
```

## How it works

For each challenge in the JSON, Hydra spawns a Docker container running `claude -p --model claude-opus-4-6` in parallel (N=8 by default). Inside the container, Claude reads `CLAUDE.md` → classifies the category → dispatches to a specialist subagent (pwn, crypto, web, rev, forensics, misc) → the specialist consults category-specific skill files and adapts exploit templates → writes the flag to `./flag.txt`. Hydra harvests the flag and writes it to `./flags.json`.

## Install

```bash
# Prereqs: Docker CE (or Podman) + Python 3.12+ + Claude Code auth
git clone <this-repo> && cd hydra
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker build -t hydra-worker .        # ~10-20 min first time
```

## Authentication

Hydra runs `claude -p` inside each Docker container. You can authenticate
two ways (subscription preferred):

### A. Claude Max / Pro subscription (preferred)

If you've already logged into Claude Code on this host (`claude login`),
your host-side `~/.claude/` directory contains the credentials. Hydra
auto-detects this and bind-mounts it into each worker container at
`/root/.claude:ro`, so the containerized `claude -p` uses your
subscription without seeing your API key at all.

```bash
# Verify you're logged in on the host:
claude --version
ls ~/.claude/   # should contain credentials.json or settings.json

# Then just run:
hydra challenges.json
```

To override the auto-detected dir, pass `--credentials-dir /some/other/.claude`.

### B. Anthropic API key (fallback)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
hydra challenges.json --use-api-key         # or let auto-detect fall through
```

The `--use-api-key` flag forces API-key mode even if `~/.claude`
exists. Without it, Hydra prefers subscription auth.

## Input format

Flexible. Hydra sniffs field names. A minimal challenge object needs `name` (or `title`/`id`) AND at least one of `description`/`task`/`prompt` or `files`/`attachments`/`paths`:

```json
[
  {"name": "baby-rsa", "description": "Decrypt this.", "files": ["/path/to/chal.py"]},
  {"name": "login",    "description": "http://ctf.example.com:8080"},
  {"name": "pwn1", "category": "pwn", "points": 200, "description": "ret2libc",
   "files": ["/tmp/pwn1"], "remote": "nc chal.example.com 1337"}
]
```

## Output

- `./flags.json` — `{name: flag, ..., "__failed__": [names]}` for direct CTF platform upload.
- `./results.jsonl` — streamed one line per finished challenge, so `tail -f` during a live comp.
- `./results.json` — final aggregate with summary stats.
- `./runs/<name>/` — per-challenge artifacts: input files, scratch, logs, flag.
- `./failures/<name>.md` — human-readable failure digest for each unsolved challenge.
- `./failures/SUMMARY.md` — index of failures.

## Common flags

```bash
hydra challenges.json \
  --parallel 8 \         # concurrent workers
  --timeout 3600 \       # per-challenge wall-clock (seconds)
  --model claude-opus-4-6 \
  --only baby-rsa,login  # run only these names
  --retry-failed         # re-run entries that previously failed/timed out
```

Resume is automatic: re-running with the same output files skips solved entries. Combine with `--retry-failed` to also re-attempt failures.

## Debugging a failure

```bash
cat failures/SUMMARY.md           # overview
cat failures/<name>.md            # per-challenge digest (postmortem + log tail)
less runs/<name>/logs/claude.stdout.jsonl  # full agent transcript
ls  runs/<name>/work/             # solver scratch files
```

## Architecture

See [`docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md`](docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md).
