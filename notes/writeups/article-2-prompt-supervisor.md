# Codify your supervisor as a prompt, not as code

*Draft v1 — follow-up to the flagship piece. Targets a more design-philosophy crowd. Publish ~7 days after flagship.*

---

## Lead

The most-debated design choice in the agent system I shipped this month is one I'd take back at the design-doc stage and one I'd defend on a whiteboard at midnight: **the supervisor isn't a Python class. It's a markdown file you paste into a second LLM session.**

Specifically: when my CTF-batch-solver agent goes off the rails — pursues a wrong attack, invents credentials it never derived, loops on a broken assumption — the system that catches it is a 230-line markdown playbook called `prompts/hydra-babysit.md` running inside a second Claude Code session. Not `judge.py`. Not `class Supervisor:`. Not a LangChain `evaluator`. Just markdown.

I've been asked twice now in DMs whether this is a "real architecture" or just "you didn't have time to write the Python." So this post is the defense, with receipts.

---

## The shape of the problem

The agent I supervise solves CTF challenges in Docker. It runs for up to 60 minutes per challenge. It can:

- Pursue the wrong attack methodology and waste 40 of those 60 minutes.
- Invent a fact ("this room's creds are `mitch:secret`") and "solve" the challenge using fabricated information.
- Hit the right oracle with the wrong payload encoding and conclude "the target is dead."
- Output a flag of the right format but with a placeholder body copied from a writeup.

Deterministic code catches some failure modes — the watchdog kills loops, the flag gate rejects malformed candidates, the verifier subagent re-checks suspect candidates. But none of those evaluate *direction*. None ask "is this agent currently barking up the wrong tree?"

That question requires an LLM. The architectural decision is **where you put that LLM and how you structure its work.**

---

## Two designs

### Design A: `judge.py`

This is what most agent frameworks ship. A Python module that:

1. Reads the worker's log at fixed intervals.
2. Constructs a prompt with the relevant log slice + a system prompt explaining the judge's role.
3. Calls the LLM API.
4. Parses the response (`<verdict>kill</verdict>` or JSON or whatever).
5. Acts on the parsed verdict (kill the container, notify the operator, etc.).

The judge's prompt is a string literal in the codebase. Maybe at the top of the file. Maybe in a `prompts/` constant. Maybe in a config YAML.

This is the obvious design. It's how `crewai`, `langgraph`, and most homebrew agent supervision systems do it. It works. I considered it for two days.

### Design B: prompt-as-supervisor

The supervisor is a separate Claude Code session. The operator pastes a long markdown playbook into that session. The playbook tells the supervisor: how to monitor, what to check, how to decide. The supervisor uses Claude Code's built-in `ScheduleWakeup` to wake periodically. It uses Claude Code's built-in `Bash` tool to run `jq` / `tail` / `stat` against the worker's log file. It uses Claude Code's built-in `docker kill` (via Bash) to enforce decisions.

The host of the supervisor is the operator's existing Claude Code session. There is no separate process, no separate auth, no separate Python module.

This is the design I shipped.

---

## Why B beats A for long-running agent supervision

Six reasons. The first three are pragmatic; the last three are architectural.

### 1. Auth is free

The supervisor uses the same Claude subscription the operator already has. No new API key, no new rate limit bucket, no new billing line. The operator pastes a prompt and gets a working supervisor in 30 seconds. With `judge.py`, you wire up an `ANTHROPIC_API_KEY` env var, decide on retry/backoff/rate-limit policy, and probably write a small auth-failure path.

### 2. Cadence is free

`ScheduleWakeup` is built into Claude Code. Tell the framework "wake me in 270s" and it does. With `judge.py`, you write a loop, a sleep, a graceful-shutdown handler, probably a systemd unit. You also write the prompt-cache-aware cadence logic from scratch (more on this below).

### 3. Workspace context is free

The supervisor has a full Claude Code environment: file editor, Bash, web search. When the supervisor needs to check the worker's log, it doesn't construct an HTTP request to an internal endpoint — it just `tail`s the file. When it needs to scrub a partial flag from `flags.json`, it `jq`s the file in place. With `judge.py`, you build either an MCP server exposing these operations, or you write a wrapper API.

### 4. Versioning is honest

`prompts/hydra-babysit.md` is a markdown file in git. `git log -- prompts/hydra-babysit.md` is the supervisor's full history. When the supervisor makes a bad call, you read the markdown, identify the row in the decision matrix that triggered, edit it, commit. The diff in PR review is literally the prompt change.

Compare to `judge.py`: the prompt is a string literal interleaved with control flow. PR diffs look like `--- old prompt line ---\n+++ new prompt line +++` inside a Python file with imports and asyncio decorators around it. Reviewers have a harder time evaluating the *prompt* change because it's tangled with code.

### 5. Domain portability is one-evening work

I built `prompts/hydra-babysit.md` for CTF batches. Then I built `prompts/bb-babysit.md` for bug bounty workflows. Same shape — pre-flight gates, cheap-check loop, decision matrix, scrub-before-commit — but every row of the decision matrix is bug-bounty-specific (out-of-scope traffic, dupe detection, WAF challenge pages).

It took an evening because the architecture is just "fork the markdown and rewrite the rows." With `judge.py`, you'd be writing a second module, deciding whether to subclass or duplicate, designing a `SupervisorConfig` abstraction, etc. Domain-portability is a refactor, not a fork.

### 6. The supervisor *is* the prompt

This is the architectural argument and the one that mattered most to me.

In `judge.py`, the supervisor is *a Python module that calls an LLM with a prompt.* The prompt is a parameter, the module is the supervisor.

In prompt-as-supervisor, *the prompt is the supervisor.* There is no Python module wrapping it. There is no separation between "the system that judges" and "the instructions that judging follows."

This matters because the prompt is the *only* thing that determines behavior. Two `judge.py` modules with the same prompt behave identically — the Python around it is plumbing. By stripping the plumbing, you make it impossible to confuse "the judge" with "the harness." When the judge makes a bad call, you fix the prompt. There's nowhere else to look.

---

## The counterarguments

To be honest, three places where `judge.py` wins:

### Cost

A naive `judge.py` can call Haiku 4.5 ($1/Mtok input). The prompt-as-supervisor design runs Opus 4.7 ($15/Mtok). On a long batch, the supervisor itself can cost as much as the worker. If you care about cost more than catch-rate, `judge.py` with Haiku is cheaper.

Mitigation: you *can* run the prompt-as-supervisor on Haiku — just open a Haiku-defaulted Claude Code session for it. But practically, most Claude Code users default to Opus or Sonnet, so without explicit configuration, the supervisor will be expensive.

### Programmatic embedding

If you're shipping a SaaS product where customers don't have Claude Code installed, the prompt-as-supervisor design doesn't help them. They need an API. `judge.py` is the right answer for that case.

This is the strongest counterargument. My setup assumes the operator is *also* a Claude Code user — true for me, not necessarily true for a B2B product.

### Determinism for compliance

In a regulated environment, you might need to demonstrate that the supervisor follows a specific deterministic decision tree. The LLM-based supervisor is probabilistic; the same input can yield different outputs. A `judge.py` with explicit `if`/`elif`/`else` is auditable in a way the prompt isn't.

Mitigation: the decision matrix in `hydra-babysit.md` is structured enough that audits are tractable, but it's not a literal state machine. If your auditors need a state machine, write one.

---

## When to use each

| Situation | Use |
|---|---|
| Long-running agent task, single operator, exploratory work | **Prompt-as-supervisor** |
| Multi-tenant SaaS, programmatic API needed | `judge.py` |
| Regulated environment requiring deterministic audit trail | `judge.py` (or both — `judge.py` for compliance, prompt-as-supervisor for engineering insight) |
| Cost-constrained, willing to trade catch-rate for cheapness | `judge.py` with Haiku |
| Pattern-portable across domains | **Prompt-as-supervisor** |
| Building a tool you want others to fork | **Prompt-as-supervisor** |

---

## How to fork the playbook

If the pattern fits your use case, the steps:

1. Copy `prompts/hydra-babysit.md` from the [Hydra repo](https://github.com/iamkorun/hydra/blob/main/prompts/hydra-babysit.md).
2. Replace the **Inputs you need before starting** section with your domain's questions.
3. Rewrite the **Pre-flight verification** section with your domain's targets (HTTP handshake? Database connection? S3 bucket policy? Kubernetes pod ready?).
4. Replace the **Decision matrix** rows with your domain's signals and actions. This is the bulk of the work. Each row is `signal → action`, and you should be able to defend every row to a skeptic.
5. Test by running it against a few simulated failure modes. The supervisor should kill / pause / continue on the right signals. If it doesn't, the playbook is wrong, not the LLM.

If you build a playbook for a domain that interests you, open an issue on the Hydra repo — the `prompts/` directory is meant to collect these.

---

## The bigger argument

A lot of "AI agent engineering" right now is people writing Python around prompts. The prompts are second-class — buried in string literals, hard to diff, hard to reuse, hard to think about.

I think the better default is to make the prompt first-class. The prompt is the contract. The prompt is the spec. The prompt is the architecture document. The Python around it is just glue, and increasingly the glue is *also* a prompt (Claude Code, Cursor agent mode, Anthropic's Computer Use harness, etc.).

When the glue is already an LLM-shaped framework, building a "judge component" in Python is a category error. You're writing imperative code for a problem that wants a prompt.

Build with prompts. Version them in git. Fork them across domains. Let the LLM frameworks do the imperative work for you.

---

*Hydra is MIT-licensed at [github.com/iamkorun/hydra](https://github.com/iamkorun/hydra). The supervisor playbook lives at `prompts/hydra-babysit.md`; the bug-bounty fork lives at `prompts/bb-babysit.md`.*
