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

Write your plan in `./work/plan.md` before running any solve code and
**update it in place** as you make progress — the file is persistent
scratch memory across tool calls, re-dispatches, and sessions.

Use PentestGPT-style hierarchical task status (`[ ] / [x] / [~] / [-]`)
with dotted outline numbering. Status markers:
- `[ ]` to-do: not started
- `[~]` in progress: started, not finished
- `[x]` completed: success criteria met
- `[-]` skipped or not applicable: the evidence ruled this path out (keep
  it for the record — don't delete — so you don't retry it)

Structure:

```markdown
# Plan: <challenge-name>

## Overall goal
<one-liner of the flag target — e.g., "recover input string that makes
./bin print the flag on stdout">

## Task tree

- [x] 1. Recon
  - [x] 1.1. `file ./challenge/*`  → ELF x86_64, stripped, not PIE
  - [x] 1.2. `strings ./challenge/bin | grep flag`  → no plaintext flag
  - [x] 1.3. `ltrace ./challenge/bin <<<AAAA`  → calls `strcmp` and `xor_block`
- [~] 2. Reverse the check
  - [x] 2.1. Identify `xor_block` address  → 0x401340
  - [~] 2.2. Determine xor key  → partial: first 4 bytes are `DEAD`
  - [ ] 2.3. Recover full key by solving constraints
- [ ] 3. Construct input
  - [ ] 3.1. Apply key to expected stored string
  - [ ] 3.2. Run ./bin with input, confirm flag on stdout
- [-] 4. Patch `jne` (fallback)   # skipped — key recovery cleaner

## Budget
- Each leaf: ~10 min or 6 failed attempts. If blown, mark `[-]` with reason
  and pick an alternate path.

## Chosen-task block (for handoff / self-reminder)

-----
Task: determine the last 12 bytes of the xor key
Command: `r2 -qc 'pdf @ 0x401340' ./challenge/bin` then read the loop constants
Expected outcome: a 16-byte constant array used in the xor; if a branch
                  compares against a stored ciphertext, derive the key by
                  reversing the xor against the known plaintext prefix.
-----
```

Keep the **chosen-task block** at the bottom (three lines bracketed by
`-----` separators) so anyone re-reading the plan knows the next concrete
action. PentestGPT uses this exact contract (`legacy/.../prompt_class_v2.py`
`process_results`).

Update the plan whenever you:
- complete a leaf (flip `[ ]` → `[x]`)
- pivot to a new leaf (update the chosen-task block)
- discover a new subtask (insert it at the right depth)
- prove a path infeasible (`[ ]` → `[-]` with a short reason)

Stale plans are worse than no plans. If the plan doesn't reflect reality,
fix it before the next tool call.

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
