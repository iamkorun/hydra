# Reddit posts — variant per subreddit

Each subreddit has different norms. Posting the HN comment text verbatim everywhere is the rookie mistake. Variants below are tuned per audience.

---

## r/netsec (security crowd, dislikes hype, loves architecture)

**Title:** `Hydra — autonomous CTF batch solver with deterministic + LLM-based supervision layers [MIT]`

**Body:**

```
TL;DR: open-source CTF batch solver, Claude Code in Docker per
challenge, with a 3-layer supervision stack designed around the
mechanical-vs-semantic failure split.

Architecture summary:

- Worker runtime: Claude Code in Docker, one container per challenge,
  triage agent dispatches to one of 7 category specialists (pwn,
  crypto, web, rev, forensics, misc).
- Layer 2 watchdog: Python sidecar tails the agent's jsonl log, kills
  on loop / OOM / cost-cap / idle. 0 token, deterministic.
- Layer 3 flag gate: REJECTs malformed flags, WARNs on missing
  derivation artifacts or prior-knowledge log.
- Layer 1 operator babysit: a separate Claude session running a
  versioned markdown playbook monitors the batch every 270s, applies
  a decision matrix (CONTINUE/KILL/UPGRADE/PAUSE), can scrub partial
  flags before they're committed.

The bug-bounty fork (prompts/bb-babysit.md) implements the same
pattern with scope-gating, dupe detection, and rate-limit enforcement
baked into the decision matrix.

Honest scope:
- Not SOTA on hard challenges; pass@k helps but the worker LLM is
  the ceiling.
- $0.50-$4 per challenge typical on Opus 4.7.
- Run only against authorized targets (CTF platforms with permission,
  your own boxes, BB programs with scope).

Repo: https://github.com/iamkorun/hydra
Long writeup: <medium link>

Happy to discuss the supervision architecture, prompt-as-supervisor
choice, or specific subagent design.
```

**Subreddit rules check:** r/netsec requires technical content, no self-promotion as primary purpose. Frame as architecture sharing, not "check out my repo."

---

## r/LocalLLaMA (AI/local model crowd, loves benchmarks + open source)

**Title:** `Built an autonomous agent that batch-solves CTF challenges with a 3-layer supervision stack — design notes inside`

**Body:**

```
After two months of running Claude Code agents against CTF
challenges, I ended up with a 3-layer supervision pattern that I
think generalizes beyond CTF.

The split:
- Mechanical failures (loops, OOM, cost overruns) → deterministic
  Python watchdog. 0 token cost.
- Semantic failures (wrong direction, hallucinated facts, partial
  outputs) → a SEPARATE LLM session running a versioned markdown
  playbook. Wakes every 270s, runs jq/tail on the worker's log,
  applies a decision matrix.

The interesting design choice: the supervisor isn't a judge.py
that calls Claude with a prompt parameter. It IS the prompt — a
230-line markdown file the operator pastes into a second Claude
Code session. Versioned in git, forkable, domain-portable.

The 270s cadence is specifically tuned to Anthropic's 5-min prompt
cache TTL. Sleeping past 300s burns the cache. 270s stays warm.
Cost difference on a 90-min batch: ~8x.

Repo (MIT): https://github.com/iamkorun/hydra
Long writeup: <medium link>

I'd love to read about how others have solved mid-run agent
direction-checking, especially folks who've tried it with open
models (Llama-3.3-70B, Qwen, etc.) — does the pattern port? My
hunch is yes if you have a structured event log to grep, no if
the agent emits free-form text only.
```

**Subreddit rules check:** r/LocalLLaMA likes self-hosted/open, slightly Claude-skeptical. Frame this as a *pattern* (LLM-agnostic) not a Claude product.

---

## r/MachineLearning (academic-leaning, demands rigor)

**Title:** `[D] 3-layer supervision pattern for long-running LLM agents (CTF case study)`

**Body:**

```
Discussion post. Sharing a design pattern I converged on after
building an autonomous CTF batch solver — happy to be told what
prior work I'm reinventing.

The problem: long-running agent tasks fail in two distinguishable
ways. (a) Mechanical — loops, OOM, runaway cost, malformed output;
detectable from outside the agent without understanding the task.
(b) Semantic — wrong direction, hallucinated facts, partial
results; require understanding the task.

The design: catch (a) with deterministic code (a sidecar watchdog
+ output validation gate, both 0-token). Catch (b) with a SECOND
LLM session running a structured "playbook" — a versioned markdown
file containing a decision matrix mapping signals to actions.

Empirically on my CTF batches, the watchdog + gate catch ~60% of
total failures (the cheap ones). The LLM supervisor catches another
~25% of failures that the watchdog misses (the semantic ones). The
remaining 15% are skill-ceiling cases the worker LLM literally can't
solve regardless of supervision — those need pass@k or human
escalation.

Open question I'm chewing on: is there a principled way to choose
the supervisor's check cadence? Currently it's tied to Anthropic's
5-minute prompt cache TTL (270s sweet spot), but the underlying
constraint is "how long can the worker drift before drift cost
exceeds check cost" — and I don't have a clean derivation of that.

Repo (MIT) with full code, playbooks, and the case study:
https://github.com/iamkorun/hydra

Looking for: (1) prior work I should cite, (2) other domains where
this pattern would or wouldn't transfer, (3) thoughts on the
cadence-derivation question.
```

**Subreddit rules check:** r/ML rule #1: tag with `[D]` for discussion. Don't lead with the repo link. Lead with the discussion question.

---

## r/securityCTF (CTF community, smaller, more product-curious)

**Title:** `Hydra: an autonomous CTF batch solver I built (MIT, Claude Code under the hood)`

**Body:**

```
Sharing a tool I've been building for batch-solving CTF challenges:
https://github.com/iamkorun/hydra

What it does: takes a JSON of challenges, spins up one Docker
container per challenge with Claude Code inside, dispatches to
category specialists (pwn/crypto/web/rev/forensics/misc), writes
flags to flags.json.

What's in the box:
- 7 specialist subagents with category-specific prompts
- ~30 skill playbooks covering RSA/ECC attacks, padding oracles,
  LFI-to-RCE filter chains, prototype pollution, anti-debug, etc.
- A "babysit" prompt for the operator to monitor the batch
  autonomously

What it won't do:
- Solve hard pwn / custom crypto without human help (those still
  benefit from a skilled CTF player)
- Be cheap — typical run is $0.50-$4/challenge on Opus

Use cases I'd actually use this for:
- Clearing easy/medium tracks of large CTFs overnight
- Smoke-testing whether a category is approachable before sinking
  time into it
- Benchmarking my own solving speed against an agent on practice
  challenges

If anyone's interested in collaborating on running this against
a public corpus (InterCode-CTF, picoCTF practice, etc.) for a
proper benchmark post, ping me — I'd like real numbers to publish
beyond "it works on my private batches."
```

**Subreddit rules check:** r/securityCTF is smaller, more relaxed. OK to be more product-pitch-shaped, but invite collaboration.

---

## r/hackernews / r/programming-style subs

Don't post to these. r/programming is hostile to LLM/AI content, r/hackernews is an HN mirror, neither helps unless you have something cross-cultural to add. Skip.

---

## Timing & strategy

- **Day 8 (1 day after HN drop):** Post r/netsec + r/LocalLLaMA simultaneously. r/MachineLearning the same day if you have time to draft a discussion-shaped post.
- **Day 9:** r/securityCTF — smaller sub, give it air, post when other channels die down.
- **Don't crosspost the same text** — each variant is tuned to its sub's norms. Crossposting verbatim is the fastest way to get karma-flagged.
- **Reply to every comment for 24h.** Reddit rewards engagement; the sub mods notice if you post and disappear.
- **Don't argue with downvotes.** Each sub has 5-10% troll/contrarian rate. Acknowledge, move on.
