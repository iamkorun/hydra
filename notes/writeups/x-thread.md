# X / Twitter thread draft

*Drop concurrently with HN, link to HN comments in the last tweet. Each tweet ≤280 chars including the image (-23 chars for the image upload).*

---

## Tweet 1 (the hook)

```
I built an autonomous CTF batch solver that runs Claude Code in
Docker per challenge.

The hard part wasn't the solving. It was keeping the agent from
going off the rails for 60 minutes while I sleep.

Here's the 3-layer supervision pattern I converged on 🧵
```

*Attach: README architecture ASCII diagram as image (or repo screenshot).*

---

## Tweet 2 (the problem)

```
After watching hundreds of agent runs, failures split cleanly into
two buckets:

• Mechanical: same Bash 7x, solve_v{1..5}.py spam, OOM, cost climb
• Semantic: wrong-tree pursuit, hallucinated facts, partial flags,
  invented credentials

These need different supervisors.
```

---

## Tweet 3 (L2 + L3 — the easy half)

```
Layers 2 and 3 catch MECHANICAL failures with deterministic Python:

• Watchdog sidecar tails the agent's jsonl log, kills on
  bash_repeat / solver_spam / cost_cap / oom / idle_work
• Flag gate vetoes malformed candidates before they hit flags.json

0 tokens. 0 LLM calls. Just regex + counters.
```

---

## Tweet 4 (L1 — the interesting half)

```
Layer 1 catches SEMANTIC failures. Needs understanding, so it's
another LLM.

But — the supervisor is NOT a Python judge.py that calls Claude.

It's a MARKDOWN FILE that the operator pastes into a separate
Claude Code session. The supervisor IS the prompt.
```

*Attach: screenshot of prompts/hydra-babysit.md decision-matrix table.*

---

## Tweet 5 (the why)

```
Why prompt-as-supervisor beats Python judge:

→ Versioned in git, forkable, reviewable
→ No new auth — uses the operator's existing Claude Code session
→ ScheduleWakeup is built-in, no cron needed
→ Domain portability is free

I wrote a second playbook for bug bounty. Same shape, different
decision rows. One evening.
```

---

## Tweet 6 (the cadence trick)

```
One detail that bit me for a month:

Anthropic's prompt cache has a 5-min TTL.

Sleeping the supervisor 300s = full re-tokenize. Cold cache. Slow.
Sleeping 270s = cache stays warm. Fast.
Sleeping 330s = worst case.

180–270s is the sweet spot. Cadence is in the prompt because it's
a judgment call.
```

---

## Tweet 7 (honest scope)

```
What this ISN'T:

• Not SOTA. pass@k helps but the worker LLM is still the ceiling
• Not cheap — $0.50–$4/challenge on Opus 4.7
• Not a CTF curriculum
• Not affiliated with Anthropic
• Not a substitute for guardrails inside the worker — additive

Don't ship to prod systems where false-positive KILL costs you.
```

---

## Tweet 8 (CTA)

```
Repo (MIT): github.com/iamkorun/hydra
Long writeup: <medium link>
HN thread: <HN link>

If you've solved agent supervision differently — especially the
mid-run direction-check problem — I want to read it. Reply with
what you've built.
```

---

## Alternate openers (test in head before posting)

**(A — the hook above):** Solving wasn't hard, supervising was. → Strongest IMO.

**(B — the receipt):**
```
50 CTF challenges, 1 JSON file, ~48 minutes, $X total cost.
Here's the autonomous batch solver that did it — and the 3-layer
supervision pattern that kept it from burning my budget on the
ones it couldn't solve.
```
→ Stronger if I had real numbers, but I don't yet.

**(C — the design choice):**
```
The most-debated design choice in my agent system: the supervisor
isn't a Python file. It's a markdown prompt running in a separate
LLM session.

Here's why prompt-as-judge beat code-as-judge for long-running
agent supervision.
```
→ Hottest take but might over-promise on debate.

**Pick A unless I get real benchmark numbers in time — then switch to B.**

---

## Timing rules

- Tuesday 8am US Pacific (same window as HN drop)
- Pin to profile for the launch week
- Don't quote-RT yourself within the first 4h — let it breathe
- DO reply-thread an update at +24h with "lessons from HN comments"
  (recyclable content)

---

## Influencer / engagement targets (mention only if they engage organically)

- @swyx — agent-tooling crowd, sometimes amplifies
- @simonw — open source / LLM tooling, often reads HN front page
- @karpathy — long shot but reads agent stuff
- @minimaxir — benchmarks-oriented; only pull if I publish numbers
- Anthropic staff who tweet (@alexalbert__, @sama_anth) — careful, don't @-spam

Don't @-mention proactively. Wait for organic discovery. @-mentions to people you haven't talked to are usually noise.
