# Changelog

## v0.1 — 2026-05-19

Initial public release.

### Architecture
- 3-layer supervision model (operator babysit + watchdog + flag gate)
- Docker container per challenge, Claude Code as worker runtime
- Triage agent dispatches to 7 category specialists

### Subagents (`.claude/agents/`)
- crypto, pwn, web, rev, forensics, misc specialists
- verifier-specialist for fabrication / hallucination detection

### Skills (`.claude/skills/`)
- ~30 attack-pattern playbooks across crypto, pwn, web, rev, forensics, misc
- 7 meta skills (decomposition, output summarization, exploit debugging, prior-knowledge gating, etc.)

### Supervision
- Deterministic watchdog with 5 signals: `bash_repeat`, `solver_spam`, `cost_cap`, `oom_preempt`, `idle_work`
- Pre-commit flag gate with REJECT / WARN / ACCEPT verdicts
- `prompts/hydra-babysit.md` operator playbook for CTF batches
- `prompts/bb-babysit.md` operator playbook for bug-bounty workflows

### Orchestration
- Parallel Docker workers (`--parallel N`)
- pass@k parallel attempts per challenge (`--attempts K`)
- Idempotent resume (`--retry-failed`)
- Postmortem markdown per failure + index in `failures/SUMMARY.md`
- Live log streaming to `logs/claude.stdout.jsonl`

### Quality
- 202 tests passing on py3.12 + py3.13
- Ruff lint clean (E + F + B + UP rulesets)
- MIT licensed
