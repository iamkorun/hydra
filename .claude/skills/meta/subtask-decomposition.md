# Subtask Decomposition

Cybench (2408.08926) showed that agents solve significantly more
challenges when a hard challenge is explicitly broken into subtasks
— even when the subtasks are the obvious ones. Do this yourself when you
sense a challenge has multiple stages.

## When to decompose

Split into subtasks when any of these are true:

1. **Multi-stage artifact** — forensics dump contains a binary → reverse
   the binary → use the binary's output as a key. Each layer is its own
   problem.
2. **Setup + exploit** — web chal needs (a) account creation, (b) auth
   bypass, (c) admin panel abuse, (d) flag read. Each with its own
   success check.
3. **Leak + pivot** — pwn chal needs (a) leak canary, (b) leak libc base,
   (c) build ROP chain, (d) pop shell.
4. **Search + solve** — an OSINT-style chal where you need to find the
   right GitHub repo first, then read its README, then decode its
   example.

If the prompt says things like "first ... then ..." you probably have a
multi-subtask challenge.

## How to decompose

Write your plan in `./work/plan.md` before running any solve code.
Structure:

```markdown
# Plan: <challenge-name>

## Overall goal
<one-liner of the flag target>

## Subtasks
1. **S1 — <name>**: <what you're trying to achieve>
   - Success check: <how you'll know this one is done>
   - Approach: <what you'll try first>
2. **S2 — <name>**: ...
   - Depends on: S1

## Budget per subtask
- S1: ~10 min or 6 failed attempts
- S2: ~15 min
- ...

## Falling back
If Sk is stuck past its budget, re-read the challenge prompt — it often
hints at the missing subtask.
```

Then work through them one at a time. Commit the plan to `./work/plan.md`
so later iterations (re-dispatches by the triage agent) see your decomp.

## Why this helps

- **Clear success checks.** Without a per-subtask check, you blur together
  "worked a little" and "done", wasting time.
- **Observable state.** Each subtask leaves artifacts in `./work/` that
  inform the next one.
- **Easier re-dispatch.** If the triage agent has to hand this back off
  to a different specialist, the subtask list is a handoff document.
- **Pivot signal.** If you can't make progress on S1 after the budget,
  that's the moment to reconsider classification or attack class — not
  30 minutes later.

## Anti-patterns

- **Over-decomposing trivial challenges.** If the prompt is "decode this
  base64", just decode it. One subtask.
- **Writing the plan but not following it.** If you've deviated from the
  plan, update the plan before continuing. The artifact is useless if
  stale.
- **Subtasks without success checks.** "Understand the binary" is not a
  subtask; "identify the address of `win()`" is.

## Reference

- **Cybench** (arxiv 2408.08926): benchmark evidence that decomposition
  doubles solve rate on hard challenges.
- **CAI** (arxiv 2504.06017): explicit "task decomposition agent" pattern.
