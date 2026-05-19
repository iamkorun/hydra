# Contributing to Hydra

Thanks for considering a contribution. The goal of this guide is to
make it cheap for you to figure out where your work fits and easy
for me to review it.

## Scope

Hydra is opinionated. The architecture is the 3-layer supervision
model (operator babysit + watchdog + flag gate), and contributions
should reinforce that split rather than blur it. If you're not
sure whether a feature fits, open an issue first — it's cheaper to
discuss than to write code that gets bounced.

## What gets merged easily

- **New specialist subagent** (e.g., `iot-specialist.md`) covering a
  category not in `.claude/agents/`. Must follow the existing
  agent-file format and include a "Top principle" section.
- **New skill playbook** under `.claude/skills/<category>/`. Same
  format as existing skills, with concrete one-liner examples and
  citations to upstream tools.
- **New exploit template** under `exploits/<category>/`. Must be
  self-contained Python (no Hydra imports), runnable standalone,
  with a docstring explaining the attack class.
- **Watchdog signal additions** in `hydra/watchdog.py`. Must be
  deterministic, 0-token, and CLI-tunable.
- **Flag gate rules** in `hydra/flag_gate.py`. REJECTs must be
  structurally provable; WARNs must be defensible to a skeptic.
- **Bug fixes** with a regression test.
- **A new playbook in `prompts/`** for a different domain (red
  team, kaggle, scraping, etc.). This is the most welcome kind of
  contribution — keep the shape consistent with `hydra-babysit.md`
  / `bb-babysit.md`.

## What requires discussion first

- Anything that touches the orchestrator's container lifecycle.
- New flag formats / changes to the flag-extractor regex.
- Anything that adds an LLM call inside the worker container
  (the worker is supposed to be self-contained Claude Code).
- Cost-model changes in `watchdog.py` (the model rate table).

## What probably won't be merged

- A web UI / dashboard. Out of scope; CLI + JSONL is the contract.
- Integration with a specific CTF platform's API. Hydra is
  platform-agnostic by design; an integration belongs in a
  separate repo that produces `challenges.json`.
- Replacing Claude Code with a different worker runtime. The
  supervision pattern generalizes, but Hydra-the-implementation
  is built around Claude Code's primitives (`ScheduleWakeup`,
  jsonl event log, MCP tools). A different worker runtime is a
  fork, not a PR.

## Development setup

```bash
git clone https://github.com/iamkorun/hydra.git
cd hydra
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/python -m ruff check
```

Tests must pass and ruff must be clean before opening a PR. CI
enforces this; check the badge at the top of the README.

## PR checklist

- [ ] Tests added / updated (regression for bug fixes, new tests
      for new features).
- [ ] `pytest` passes locally.
- [ ] `ruff check` is clean.
- [ ] If you touched a `.claude/agents/*` or `.claude/skills/*`
      file, the change is consistent with the agent-file format.
- [ ] If you touched `prompts/hydra-babysit.md`, the decision
      matrix still parses as a table.
- [ ] You haven't committed any real CTF flags or credentials.
      Test fixtures use illustrative-only values
      (`flag{w1ener_w1ns}`, `198.51.100.x`).

## Forks of the supervision playbook

If you forked `prompts/hydra-babysit.md` for a different domain
(red team, ML competition, scraping pipeline, etc.) — **please
open an issue** even if you're not planning to upstream it. The
goal is for the `prompts/` directory to be a catalog of
supervision patterns across domains; knowing who's forking is
useful even if your fork stays on your repo.
