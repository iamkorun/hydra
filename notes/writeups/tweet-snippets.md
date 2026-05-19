# Tweet snippets — per-article amplification

When each Medium article publishes, drop a 2-3 tweet teaser thread
that quotes the article's strongest line + links. Pre-written below.

---

## For Article #1 (flagship — "The supervisor is a prompt")

**Tweet 1:**
```
New writeup: I spent two months building an autonomous CTF batch
solver, and the architectural insight that stuck wasn't about
CTF.

It was about agent supervision. Specifically: your LLM judge
should be a markdown file, not a Python module.

<link>
```

**Tweet 2:**
```
The split that matters: mechanical failures (loops, OOM, cost
overruns) get deterministic Python. Semantic failures (wrong
direction, hallucinated facts) get a SEPARATE LLM session
running a versioned playbook.

3 layers, 2 of them 0-token.
```

**Tweet 3:**
```
The playbook lives in prompts/hydra-babysit.md — 230 lines of
markdown the operator pastes into a second Claude Code session.

Versioned in git. Forkable. Domain-portable.

I already shipped a bug-bounty fork using the same shape.
```

---

## For Article #2 ("Codify your supervisor as a prompt, not as code")

**Tweet 1:**
```
Most-debated design choice in my agent system: the supervisor isn't
a Python class. It's a markdown file you paste into a second LLM
session.

Defense thread for why prompt-as-supervisor beats judge.py:

<link>
```

**Tweet 2:**
```
The architectural argument: in judge.py, the supervisor is "a
module that calls an LLM with a prompt." The prompt is a parameter.

In prompt-as-supervisor, the prompt IS the supervisor. There is no
Python module around it.

That difference is load-bearing.
```

**Tweet 3:**
```
When you separate "the system that judges" from "the instructions
that judging follows," you create two places to look when the
supervisor makes a bad call.

When you collapse them, there's only one place. Fix the prompt.
That's it.
```

---

## For Article #3 ("The 270-second sweet spot")

**Tweet 1:**
```
For about a month my LLM agent supervisor was burning ~3× more
tokens than necessary.

Not because the prompt was wrong. Because it was waking every
5 minutes.

Why 5 minutes is the WORST possible cadence for LLM supervisor
loops, and what to pick instead.

<link>
```

**Tweet 2:**
```
Anthropic prompt cache TTL: 5 min.

Sleep 270s → cache stays warm → 10% of input cost.
Sleep 300s → cache expires → 100% of input cost.
Sleep 330s → cache long gone → 100% of input cost + wasted wall time.

The sweet spot is just under the TTL with margin for clock drift.
```

**Tweet 3:**
```
The bigger lesson: cadence is a *cost* decision shaped by an
architectural constraint (cache TTL), not a UX decision ("how often
do I want to be checked on").

Look at your agent system's knobs. The ones you set once and forgot
are usually load-bearing in ways you haven't acknowledged.
```

---

## Quote-tweet candidates

Pre-saved formulations to quote-tweet your own launch tweets or others'
relevant posts during the launch week.

**Self-amplification (reply to your own X thread at +24h):**
```
24h update on the supervision-pattern thread: top question in DMs is
"why not just OpenAI / Llama / Gemini?"

The pattern is LLM-agnostic. The harness happens to be Claude Code
because ScheduleWakeup + subscription auth removes friction. Anyone
porting? I want to read it.
```

**If someone tweets about agent supervision generically:**
```
Quote-tweet template: "Same problem hit me. Wrote up the pattern I
landed on after 2 months on a CTF batch solver — 3-layer split,
deterministic + LLM-prompt judge. Repo + writeup: <link>"
```

**Don't quote-tweet Anthropic's tweets** unless they explicitly
mention agent supervision and your context is additive. Looks like
piggybacking otherwise.
