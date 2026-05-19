# The 270-second sweet spot: prompt-cache-aware cadence for LLM supervisors

*Draft v1 — technical deep-dive piece. Publish ~14 days after flagship. Targets the prompt-engineering / agent-tooling crowd specifically.*

---

## Lead

For about a month, my LLM agent supervisor was burning ~3× more tokens than it needed to. Not because the prompt was bad. Not because the decision matrix was wrong. Because the supervisor was sleeping for 5 minutes between checks.

This post is about why "5 minutes" is the single worst cadence you can pick for a long-running LLM supervision loop, what to pick instead, and how the prompt cache TTL shapes the entire design of agent-checking systems.

---

## The system

To set context briefly: I run a CTF-batch-solver agent in Docker. A second Claude Code session, primed with a markdown playbook, monitors the batch. The supervisor wakes periodically using Claude Code's `ScheduleWakeup` primitive, runs `jq` / `tail` against the worker's log file, applies a decision matrix, and either continues / kills / pauses / upgrades the worker.

The "wakes periodically" part is the part this post is about.

---

## Why cadence matters at all

Every wake-up has a cost. The supervisor:

1. Loads its accumulated conversation context (prompt + history).
2. Reads the worker's log via `jq`/`tail`.
3. Reasons about the new state.
4. Either acts or schedules the next wake.

Step 1 is the expensive step. The supervisor's conversation grows over the duration of a batch — it's the same session running for an hour, accumulating decisions. Re-tokenizing that context every wake costs real money.

This is where the **prompt cache** comes in.

---

## The Anthropic prompt cache, briefly

Anthropic offers automatic prompt caching: if the model sees the same prompt prefix it saw recently, it skips re-processing that prefix and reads from cache. Cached input tokens cost 10% of the regular rate.

The cache TTL is **5 minutes**. (Anthropic offers a 1-hour cache for an additional cost, but the default is 5 minutes.)

This means: if your supervisor wakes 4 minutes after the last wake, the cache is hot and the wake is cheap. If it wakes 6 minutes after, the cache is gone and the wake reprocesses the full conversation at full cost.

---

## The naive cadence

When I first built the supervisor, I picked "5 minutes" as the check interval. It felt right — quick enough to catch problems, slow enough not to spam. A reasonable default.

**It is the single worst possible cadence.**

Here's why. The cache TTL is 5 minutes. If I wake at exactly 300s, I'm:

- Past the TTL by 0-2 seconds (because clocks drift, network latency exists, the actual elapsed time is rarely *exactly* 300s).
- Paying the full re-tokenization cost.
- Amortizing that cost over... 5 minutes of supervision. Then doing it again.

For a 90-minute batch, that's ~18 cache misses. At Opus rates with a ~30k-token accumulated conversation, that's ~$8 in cache misses alone.

If I'd picked 270s instead:

- Comfortably inside the 5-minute TTL.
- Cache stays hot.
- ~$1 in input costs for the same 90-minute supervision.

**Same supervisor. Same playbook. Same catch-rate. 8× the cost difference based on cadence.**

---

## The two regimes

Once you internalize the cache TTL, two regimes emerge:

### Regime A: 60-270s (cache-warm)

For active supervision — when the worker is actively running and you want to catch problems within a minute or two of them appearing — pick a cadence under 300s. **270s is the sweet spot**: comfortably under the TTL with margin for clock drift, but not wastefully short.

Within this regime, shorter is fine. 180s costs about the same as 270s because both stay in cache. Pick 180s if you want tighter catch latency. Pick 270s if your decision matrix doesn't have failure modes that emerge within 180s of starting.

### Regime B: 1200-3600s (idle / human-in-loop)

For supervision during human review — when the supervisor is waiting for the human to read a flagged candidate, approve a report, or redeploy infrastructure — pick a cadence over 1200s.

Why 1200s and not 900s or 600s? Because at this regime you're explicitly OK with the cache miss. The supervisor isn't doing meaningful work; it's just checking that nothing has changed. You might wake once or twice per hour. The cache miss is amortized over 20+ minutes of "supervisor doing nothing" so the per-supervision cost is fine.

The reason to not pick 600s is that 600s is the worst-of-both: you pay the cache miss every 10 minutes, but you also don't get to amortize over a long idle period.

### Don't pick 300-900s

This range is a dead zone. You pay the cache miss every wake, but you also don't sleep long enough to make the miss worth it. If you find yourself tempted to pick "5 minutes" or "10 minutes," resist. Drop to 270s if you need tight latency, or jump to 1200s+ if you're idle.

---

## Cadence as a judgment call

Here's where it gets interesting: cadence isn't a constant in the supervisor. It's a *decision the supervisor makes per wake.*

The `hydra-babysit.md` playbook has this line:

> Tighten to 180s if you suspect rapid loop/failure. Relax to 270–360s once stage is clearly progressing.

The supervisor's last action on each wake is to schedule its next wake. It picks the duration based on its read of the worker's state:

- Worker is rapidly producing new tool-uses with novel signals → 270s (cache-warm, can afford longer because state is changing slowly enough that I won't miss anything in 4 minutes)
- Worker is producing tool-uses but they look repetitive → 180s (tighten — might be a loop forming)
- Worker just hit a watchdog kill or operator pause → 1800s (idle — wait for operator decision)
- Candidate finding is ready for human review → 1800-3600s (idle — wait for human)

Cadence is a continuous knob the supervisor turns based on its judgment. The playbook tells it *how* to turn the knob, not what value to use.

This wouldn't be possible in a typical `judge.py` design — the loop cadence is usually a constant, set at process startup. The LLM-based supervisor naturally varies its own cadence based on the situation, because picking the next wake duration is just one more decision in its loop.

---

## What this generalizes to

The 270s number is specific to Anthropic's 5-minute cache TTL. If you're running an OpenAI- or Gemini-based agent supervisor, look up the cache TTL of your provider.

- OpenAI's prompt cache TTL (as of 2026): variable, but typically 5-10 minutes. You'd want to wake at ~80% of whatever the cache holds for in your account tier.
- Gemini: their cache is explicit (not automatic). You set the TTL yourself, then design cadence around it.
- Self-hosted: KV cache lives in GPU memory and is essentially infinite-TTL as long as the server doesn't restart. You can sleep arbitrarily, just make sure the worker shares the same server.

The general principle: **find the cache TTL of your stack, and pick a cadence at ~80-90% of that.** Avoid the dead zone of 1.0-3.0× the TTL.

---

## The bigger lesson

When I was designing the supervisor, I treated cadence as a UX decision — "how often do I want to be checked on?" It turned out to be a *cost* decision shaped by an architectural constraint I hadn't internalized.

A lot of agent-system engineering looks like this: a knob that seems orthogonal to performance is actually load-bearing once you understand the underlying mechanism. Token cost, latency, catch-rate, and cadence are all coupled through the cache TTL.

Look at your agent system's knobs. Find the ones you set once and forgot. Ask whether any of them are coupled to a constraint you haven't acknowledged.

There's usually a 270-second sweet spot in there somewhere.

---

*Hydra is MIT-licensed at [github.com/iamkorun/hydra](https://github.com/iamkorun/hydra). The cadence logic — and the rest of the supervisor playbook — lives at `prompts/hydra-babysit.md`.*
