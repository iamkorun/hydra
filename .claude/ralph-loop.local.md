---
active: true
iteration: 1
session_id: 
max_iterations: 25
completion_promise: "HYDRA_AUDIT_COMPLETE"
started_at: "2569-04-14T10:47:59Z"
---

You are auditing and improving the Hydra CTF solver at /home/muffin/me/ctf/hydra (private repo https://github.com/iamkorun/hydra). P1 is complete (30 tasks, 64 tests passing). Check git log to see history. Track your progress in .claude/.audit-progress.md across iterations. When every item below is truly done (verified by tests), output <promise>HYDRA_AUDIT_COMPLETE</promise>.

## Checklist

### 1. AUTH: switch from ANTHROPIC_API_KEY to 'claude -p' subscription auth
- Current: hydra/docker_worker.py passes '-e ANTHROPIC_API_KEY=...'
- Target: bind-mount the host's Claude Code credential dir into the container so 'claude -p' uses the host's logged-in subscription. Typical host path: ~/.claude/ (contains credentials). Mount at /root/.claude/:ro.
- Update hydra/cli.py: stop requiring ANTHROPIC_API_KEY env var; require ~/.claude exists (with credentials file). Keep ANTHROPIC_API_KEY as an optional fallback.
- Update hydra/docker_worker.py: accept a new parameter 'credentials_dir: Path | None' and mount it. If None, fall back to api_key env.
- Update OrchestratorConfig + tests.
- Update Dockerfile if needed.
- Update README.md.

### 2. PAPER SKILLS — ensure patterns from EnIGMA, Cybench, NYU CTF Bench, Palisade, CAI exist
Prioritize CAI (arxiv 2504.06017). For each pattern, check if it already exists; if not, add:
- **Tmux persistent sessions** (EnIGMA 2409.16165, NYU 2406.05590): .claude/skills/pwn/tmux-session.md showing 'tmux new-session -d -s pwn' + 'tmux send-keys' + 'tmux capture-pane' for long-lived nc/remote connections. Add 'tmux' to docker/apt-packages.txt if missing.
- **Subtask decomposition** (Cybench 2408.08926): .claude/skills/meta/subtask-decomposition.md — when and how to split a single chal into subtasks.
- **Plain-agent ReAct first** (Palisade 2412.02776): audit each specialist prompt to ensure they try simple shell-first before reaching for heavy tooling. Add 'Try shell first' as a top principle in each specialist.
- **Multi-agent + memory** (CAI 2504.06017): add notes/lessons-learned.md scaffold. Update CLAUDE.md to instruct 'append a one-line lesson to notes/lessons-learned.md when you solve something nontrivial or discover a gotcha'. Add notes/ to .gitignore? No — keep it tracked.
- **Interactive agent tools** (EnIGMA): document the pattern in .claude/skills/meta/iat-pattern.md (how to wrap interactive tools like gdb/r2 console with tmux).

### 3. FIX P1 DRIFT
- Restore 'failed' vs 'error' status distinction in hydra/orchestrator.py: exit_code != 0 → 'error'; exit_code == 0 + no flag → 'failed'. Update integration test (tests/integration/test_pipeline.py test_mixed_batch) to assert 'error' for the exit_code=1 case.
- Keep the flag extractor's negative-lookbehind fix.

### 4. SCAN & FIX ISSUES
- .venv/bin/pytest -v must pass (currently 64). New tests must pass too.
- Install ruff if missing: .venv/bin/pip install ruff
- Run: .venv/bin/ruff check . --fix (auto-fix) and .venv/bin/ruff check . (report remaining). Fix any remaining issues that aren't stylistic bikesheds.
- Check Dockerfile for correctness (no actual build — just read).
- Check all specialist prompts reference valid .claude/skills/ and exploits/ paths. Fix any that point at non-existent files.
- Verify exploit templates all ast.parse cleanly: .venv/bin/python -c 'import ast, pathlib; [ast.parse(p.read_text()) for p in pathlib.Path("exploits").rglob("*.py")]'

### 5. ADD NEW TESTS for the above
- Test for credentials_dir mount logic in docker_worker.
- Test for failed-vs-error status distinction.
- Commit each logical change.

### 6. WRITE AUDIT REPORT
Create docs/audit-2026-04-14.md with:
- ## Critical issues found (must fix) — with fix status
- ## High concerns (should fix) — with fix status
- ## Medium concerns (consider fixing) — not necessarily fixed; just listed
- ## Out-of-scope / follow-ups
List EVERY medium+ concern you find, even if out of scope.

### 7. PUSH
After everything green, 'git push'.

## Iteration rules
- Each iteration, read .claude/.audit-progress.md first. Check off what's done. Identify the NEXT undone item. Do ONLY that item. Update progress. Commit.
- If a test breaks, fix it before proceeding.
- If you can't make progress (blocked), add a detailed note to .claude/.audit-progress.md and mark that item BLOCKED — move to next item.
- When every item is DONE (ideally also BLOCKED items have resolution plans documented), verify with a final full test run, then emit <promise>HYDRA_AUDIT_COMPLETE</promise>.

Working directory: /home/muffin/me/ctf/hydra
Venv Python: .venv/bin/python
Venv pytest: .venv/bin/pytest
Git: commit each logical change with conventional-commit message ('feat:', 'fix:', 'refactor:', 'docs:', 'test:').

