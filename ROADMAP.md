# Roadmap

Public-facing direction for Hydra. Specific commits and timelines
intentionally fuzzy — this is a *direction* document, not a schedule.

## Shipped (v0.1)

- 3-layer supervision (operator babysit + watchdog + flag gate)
- 7 specialist subagents covering pwn, crypto, web, rev, forensics, misc
- ~30 skill playbooks ([`.claude/skills/`](.claude/skills/))
- pass@k parallel attempts with first-flag-wins cancellation
- Deterministic watchdog signals: `bash_repeat`, `solver_spam`, `cost_cap`, `oom_preempt`, `idle_work`
- Pre-commit flag gate with REJECT/WARN/ACCEPT verdicts
- Bug-bounty playbook fork (`prompts/bb-babysit.md`)
- 202 tests, CI on py3.12 + py3.13

## Next (v0.2 — targeted at 1-2 months out)

- **Benchmark on a public corpus.** Run Hydra against InterCode-CTF
  and publish the numbers. Right now the README claims pass@k helps
  by citing Palisade; v0.2 will cite *our own* numbers too.
- **`hydra supervise` subcommand.** Today the babysit playbook is a
  manual paste into a separate Claude Code session. v0.2 wraps it so
  the supervisor can be spawned as a sibling process to the batch.
  The playbook stays as the source of truth; the subcommand is a
  thin convenience wrapper.
- **Per-category cost telemetry.** Today `cost_cap` is a single
  number per challenge. v0.2 surfaces per-category cost rollups so
  operators can budget by category (pwn is more expensive than
  misc, currently invisible).
- **Cheaper supervisor option.** "Hydra on Haiku" — document and
  test running the babysit playbook on Claude Haiku 4.5 to cut the
  supervisor's own cost ~5×. The playbook works on Haiku; the
  question is whether the catch-rate stays acceptable.

## Later (v0.3+, no timeline)

- **Resumable batches across machines.** Today `--retry-failed`
  works only on the same machine. v0.3 would let you pause a batch
  on machine A and resume it on machine B given just the results
  directory.
- **Additional category specialists.** IoT / firmware / hardware
  if the community brings real CTF artifacts to test against.
- **Open-model worker.** Document running the worker side on
  open models (Llama-3.3-70B-Instruct, Qwen-72B) instead of Claude
  Code. The supervision pattern is LLM-agnostic; the *worker*
  harness needs porting.
- **More playbook forks.** Specifically interested in: red-team
  engagement supervisor, kaggle ML competition supervisor,
  long-running scraping pipeline supervisor. PRs welcome.

## Won't do

- **Web UI / dashboard.** CLI + JSONL is the contract. The
  `.local/launch-status.html` style is the only UI I find useful.
- **CTF platform integration.** Hydra reads JSON; converting from
  CTFd / HackTheBox / picoCTF to JSON belongs in a sibling repo.
- **Custom LLM hosting.** Hydra invokes Claude Code; the model
  hosting is Anthropic's problem.

---

This file is loosely maintained. For concrete planned work, watch
the [issues](https://github.com/iamkorun/hydra/issues) labeled
`v0.2` and `v0.3`.
