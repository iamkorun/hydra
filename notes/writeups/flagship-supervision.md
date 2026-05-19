# The supervisor is a prompt: a 3-layer pattern for keeping LLM agents on-track

*Draft v1 — flagship Medium piece for Hydra launch*

---

## Lead

You hand an LLM agent a long-running task — solve 50 CTF challenges, hunt a bug bounty, refactor a 300k-line monorepo — and walk away. An hour later, half the work is done, a quarter is silently wrong, and a quarter is the agent looping on a single broken assumption while burning your token budget at $0.30/min.

This is the single hardest problem in production agent systems right now. Not "can the model solve the task" — modern Claude / GPT / Gemini frontier models can solve most of what you'd reasonably hand them. The hard problem is: **how do you catch the agent when it goes off the rails, without standing over its shoulder?**

I spent two months building [Hydra](https://github.com/iamkorun/hydra) — an autonomous CTF batch solver that runs Claude Code in a Docker container per challenge — and the answer I converged on was: **three supervision layers, two of them deterministic code, one of them a prompt running in a separate LLM session.**

This post is about why that split is the right shape, and what I learned codifying the LLM supervisor as a versioned prompt instead of as Python.

---

## The setup: what Hydra does

Hydra takes a JSON file of CTF challenges and produces a JSON file of flags:

```
hydra challenges.json
# ✓ baby-rsa    → flag{w1ener_w1ns}  (47s)
# ✓ login       → flag{sqli_r0ck5}   (2m13s)
# ✗ pwn2        → (timeout after 60m)
#
# solved 42/50 in 48m21s → ./flags.json
```

Each challenge runs in its own Docker container with Claude Code inside. A triage agent classifies the category (pwn / crypto / web / rev / forensics / misc), dispatches to a specialist subagent, and writes the flag to a known path. Hydra harvests across the whole batch.

That's the boring part. The interesting part is what happens when an agent decides — confidently — to spend 47 minutes trying to break RSA with Wiener's attack on a challenge that is actually just `base64(rot13(flag))`.

---

## Two kinds of failure

After watching hundreds of agent runs, I noticed failures cluster into two cleanly separable buckets:

**Mechanical failures** are observable from the outside without understanding the task:
- Same Bash command fires 7 times in a row
- Five `solve_v{1..5}.py` files appear in `work/`, all virtually identical
- Token spend crosses $10 with no flag in sight
- The container's RSS climbs past 90% of its memory limit
- The `work/` directory stops changing while the agent is still producing assistant messages

You don't need to understand RSA, Modbus, or prototype pollution to detect these. They're cheap signals, regex-grep-able from the agent's log stream. They're 100% deterministic.

**Semantic failures** require understanding the task:
- Agent is barking up the wrong tree — committed to algebraic attack when brute force would finish in 30s
- Agent invented a fact: "this room's creds are `mitch:secret`" — pulled from training memory, not from the actual challenge
- Agent hit the right oracle but with the wrong payload encoding and concluded "target dead"
- Agent recorded a flag of the right format but the body is a placeholder string copied from a writeup
- Agent is making progress on Stage 1 but Stage 1 is a red herring

You cannot regex these. Detecting them requires *understanding what the agent is doing*. The cheapest way to get understanding into the loop is another LLM.

---

## The supervision stack

Hydra's three layers map directly onto this split:

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

**Layer 2** (watchdog) and **Layer 3** (flag gate) catch mechanical failures. Pure Python. Zero LLM calls. Documented in `hydra/watchdog.py` and `hydra/flag_gate.py` if you want to read 600 lines of asyncio + regex. The interesting part is Layer 1.

---

## Layer 1: the supervisor is a prompt

Layer 1 is where most "AI agent supervision" projects get this wrong. They either:

(a) Don't bother — let the agent run, hope, audit at the end.

(b) Build a Python `judge.py` that calls Claude every N seconds with a hard-coded prompt.

Hydra does neither. Layer 1 is **a markdown file** — `prompts/hydra-babysit.md` — that the operator pastes into a *separate* Claude Code session. That session monitors the batch.

This is a strange-feeling design choice. Let me argue it.

### What the babysit prompt contains

The prompt is ~230 lines covering:

- **Pre-flight verification** — before launching a worker, verify the target's protocol handshake (not just port-open). Defends against IP recycling on platforms where one IP can serve the wrong challenge after a redeploy. Includes one-liners per protocol (HTTP, Modbus, BACnet, EtherNet/IP).
- **Cheap-check loop** — wake every 180–270s (prompt-cache sweet spot — see below). Per wake, run `jq` / `tail` / `stat` against the agent's jsonl log. Never `cat` the whole transcript — it's multi-MB and burns context.
- **Decision matrix** — first-matching-row dispatch over CONTINUE / KILL / UPGRADE (sonnet → opus) / PAUSE on a defined list of signals.
- **Scrub-before-commit** — if Hydra already recorded a partial / wrong flag, scrub `flags.json` and downgrade `results.jsonl` so `--retry-failed` can re-pick the challenge.
- **Anti-patterns** — explicit list of things the supervisor must NOT do (don't auto-restart after kill, don't `cat` large logs, don't fight WAFs).

### The decision matrix excerpt

```
| Signal | Action |
|---|---|
| Full flag matching expected format in flags.json | DONE. Notify user, stop loop. |
| Target port refused / "No route to host" mid-run | PAUSE. Kill container cleanly, ask user to redeploy. |
| Banner of wrong challenge (e.g. wrong product string) | PAUSE immediately. IP was recycled. |
| Partial-looking flag in flag.txt AND agent text says "this is the flag" | KILL before hydra records it. Scrub flags.json. |
| Same Bash command repeated 3+ times with no new diagnostic | KILL. API loop, not progress. |
| Agent invents facts not in challenge files | KILL. Hallucination. |
| Working connection + correct methodology + wrong output after 2-3 iterations | UPGRADE sonnet → opus. |
| Cost over cap without a flag | KILL. Report to user. |
| Everything healthy | CONTINUE. Schedule next wake. |
```

This is deterministic *judgment*. The supervisor LLM doesn't freelance — it's running a decision tree against signals it grades from the worker's log. The LLM's job is interpreting "is the current Bash spam *actually* a loop, or is it genuine retry-with-backoff?" — which is the semantic question. The action is then mechanical.

### Why this beats a Python judge

A common alternative architecture: build `judge.py`, call Claude API with the worker's log every N seconds, parse `<action>KILL</action>` from the response. This is the "obvious" engineering answer. It's also worse for these reasons:

**The supervisor is the same Claude Code session that the operator already uses for everything else.** They don't need a new auth, a new API key, or a separate Anthropic API rate limit bucket. The supervisor uses the operator's subscription, shares context with their existing session if they want, and lives in the same UX as their normal work.

**The prompt is versioned in git, forkable, and reviewable.** When the supervisor makes a bad call, you read the markdown to find the decision row that triggered, edit it, and commit. With a Python judge, you'd be touching prompt strings embedded in code — uglier diffs, more friction.

**Domain portability is free.** I built a second playbook, `prompts/bb-babysit.md`, for bug bounty hunting. Same shape — pre-flight gates (scope.json), cheap-check loop, decision matrix — but every row is bug-bounty-specific (out-of-scope traffic, dupe detection, WAF challenge pages). It took an evening, not a sprint, because the architecture is just "fork the markdown."

**ScheduleWakeup is built into Claude Code.** The supervisor doesn't need a cron, a systemd timer, or a background process. It tells the framework "wake me in 270s" and the framework wakes it. The framework also handles the prompt cache.

### The 270s sweet spot

One detail worth surfacing: I cargo-culted "5 minutes" as the supervisor check interval for the first month, then realized it was the worst possible cadence.

Anthropic's prompt cache has a 5-minute TTL. Sleeping past 300s means the next wake-up reads the whole conversation context uncached — much slower and more expensive. Sleeping just under (270s) keeps the cache warm. Sleeping just over (330s) eats the full re-tokenize cost.

So the supervisor wakes every **180–270s** when the worker is active, and stretches to **900–1800s** when the human is reviewing a candidate. Cadence is in the prompt because cadence is a judgment call, not a constant.

---

## What this isn't

Two clarifications I owe up front:

**This isn't a replacement for guardrails inside the worker.** The worker still has its own discipline (`plan.md`, exploit-debug ladder, no-prior-knowledge audit log) — those catch local mistakes the supervisor wouldn't see. The 3-layer model is *additive*, not a substitute for getting the worker prompt right.

**This isn't optimized for cost.** A naive `judge.py` could be cheaper if you used Haiku and only ran every 5 minutes. Hydra's supervisor uses Opus 4.7 by default because the decision matrix asks subtle questions ("is this a meaningful retry or a loop?") that benefit from the bigger model. If cost matters more than catch-rate, swap the supervisor to Haiku — the playbook still works.

---

## Try it

Hydra is open source, MIT-licensed:

> https://github.com/iamkorun/hydra

The flagship artifact for this post — `prompts/hydra-babysit.md` — is in the repo. Fork it. Edit the decision matrix for your domain. If you build a supervisor playbook for something else (red-team engagement, kaggle-style ML competition, long-running scraping pipeline), open an issue — the `prompts/` directory is meant to collect these.

If you're working on agent supervision and want to compare notes, I'm reachable at the repo's issues.

---

## Appendix: when *not* to use this pattern

The 3-layer model has real overhead. Skip it for:

- **Single-shot agent calls** — no long-running task, no monitoring needed.
- **Tasks under 5 minutes** — by the time you set up supervision, the work is done.
- **Production systems with strict SLAs** — you want deterministic everything; pull the LLM supervisor out and rely solely on Layers 2 + 3, even if you miss semantic failures.
- **Anywhere you can't tolerate a supervisor making a wrong call** — KILL/UPGRADE/PAUSE has a non-zero false-positive rate. That's fine for CTF batches (re-run the challenge) and fine for bug bounty (re-launch with corrected hypothesis), not fine for "deploy to production."

For everything in between — agents running 10 min to 10 hours, with a human who'd like to walk away but not blindly trust — this is the pattern I'd reach for now.

---

*Hydra is built on Claude Code as the worker runtime; it is not affiliated with Anthropic. The 3-layer supervision pattern generalizes beyond Claude — same approach works with any LLM agent that emits a structured event log.*
