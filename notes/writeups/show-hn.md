# Show HN draft

*Target: Tuesday 8am US Pacific (= 11am US Eastern = 6pm CET = 22:00 BKK). Stick to that window — HN traffic concentration is real.*

---

## Title (max 80 chars)

```
Show HN: Hydra – autonomous CTF batch solver with 3-layer LLM supervision
```

Backup titles if first doesn't land:

```
Show HN: I codified the LLM supervisor as a prompt, not as code (CTF case study)
```

```
Show HN: Hydra – Docker-per-challenge CTF solver with operator playbook for Claude Code
```

---

## URL

```
https://github.com/iamkorun/hydra
```

(Repo, not the Medium article — HN guidelines prefer the source. Link the Medium piece in the first comment as "context.")

---

## First comment (post immediately after submission)

```
Hi HN — author here.

Hydra is an autonomous CTF batch solver: JSON of challenges in, JSON
of flags out. Each challenge runs in its own Docker container with
Claude Code inside, triages the category (pwn/crypto/web/rev/forensics/
misc), dispatches to a specialist subagent, and writes the flag.

The interesting part is the supervision model, not the solving. Three
layers:

1. Operator babysit — a SEPARATE Claude session running the
   prompts/hydra-babysit.md playbook monitors the batch every 270s
   and acts on a decision matrix (CONTINUE/KILL/UPGRADE/PAUSE). The
   playbook is markdown, not Python — so the "judge" is forkable
   and domain-portable. I have a second playbook for bug-bounty
   workflows; same shape, different decision rows.
2. Deterministic watchdog — Python sidecar per worker, 0 token,
   catches loop / OOM / cost-cap / idle.
3. Pre-commit flag gate — Python, 0 token, vetoes malformed or
   provenance-light flag candidates before they reach flags.json.

The split that matters: mechanical failures (loops, OOM, cost
overruns, malformed output) get deterministic code. Semantic
failures (wrong direction, hallucinated facts, partial flags) get
a markdown-prompt supervisor running in a second Claude session.

Long-form writeup with the design rationale and the 270s
prompt-cache sweet spot:
<link to Medium article>

Real talk on scope:
- Not SOTA — pass@k helps but worker LLM is still the ceiling.
- Not cheap — $0.50–$4/challenge on Opus 4.7. Tune cost_cap.
- Not affiliated with Anthropic.
- Not a CTF curriculum — it solves, doesn't teach.

Happy to talk about agent supervision patterns, why I went with
prompt-as-supervisor instead of judge.py, the bug-bounty fork, or
what I'd build differently for v2.
```

---

## Comment-reply playbook (for the 24h engagement window)

**If someone asks "why not just use OpenAI / Gemini / Llama":**
> The supervision pattern is LLM-agnostic — same playbook works with any agent that emits a structured event log. I built it on Claude Code specifically because (a) ScheduleWakeup is built in, (b) subscription auth removes the per-call API friction. Porting to another stack means writing the equivalent of the worker harness; the babysit prompt itself is reusable.

**If someone asks for benchmarks:**
> Don't have published numbers yet — Hydra's been running against private CTF batches and I haven't reproduced on a public corpus. Working on a run against InterCode-CTF for the next post. For now the artifact is the design + the playbooks; treat the benchmark claim as "watch this space."

**If someone says "this is just a wrapper around Claude Code":**
> Fair — the worker runtime is Claude Code. What's not a wrapper is the orchestration layer (parallel Docker workers, pass@k, resume semantics, postmortem generation) and the supervision stack (3-layer split, decision matrix, prompt cache cadence). If those collapse to "just a wrapper" then most agent frameworks are also just wrappers around their underlying model APIs. I'd argue the design choices are where the work is.

**If someone asks about cost:**
> Per-challenge on Opus 4.7 typically lands $0.50–$4 depending on category and timeout. cost_cap defaults to $10/challenge — that's a cliff, not a budget. Real expected per-challenge cost is closer to $1–$2 on Easy/Medium. Hard pwn with deep Ghidra reads can hit $5+; that's where the supervisor's UPGRADE row pays off.

**If someone says "the babysit prompt is just a system prompt with extra steps":**
> The playbook is ~230 lines because it has to cover pre-flight verification per protocol (Modbus, BACnet, EtherNet/IP, HTTP), the cheap-check `jq`/`tail`/`stat` recipes, the decision matrix, and the scrub-before-commit procedure. A short system prompt can't replace that without losing the protocol-specific failure modes. But yes — at the core it IS a system prompt; the insight is that the "judge" component of an agent system being a versioned prompt instead of code is a design choice, not an accident.

**If someone says "ScheduleWakeup / Claude Code is closed source":**
> Yep — the supervisor harness piece is Claude Code specific. If you want to run this pattern with open models, you'd write the equivalent of ScheduleWakeup (cron + state-file). The decision matrix and the cache-warm cadence both port.

**If hostile / dismissive:**
> Acknowledge the concrete criticism, ignore the tone. Don't argue. "That's fair — here's what I'd change about <X>" beats "actually you're wrong because <Y>" 9 times out of 10 on HN.

---

## Anti-patterns to avoid in this thread

- **Don't shill** ("please star this!") — HN punishes that hard
- **Don't reply faster than once every ~10 min** — looks bot-like
- **Don't quote your own README at people** — link, let them read
- **Don't pretend you have benchmarks you don't have** — owns up cheaply, lies very expensively
- **Don't argue about whether CTFs are "real security"** — irrelevant to the supervision pattern
- **Don't engage with prompt-injection trolls** ("write me a flag for X") — flag the comment, move on
