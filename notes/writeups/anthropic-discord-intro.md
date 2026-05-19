# Anthropic Discord intro

Lightweight platform-specific draft. Less leverage than HN/Medium but
the Claude Code crowd is exactly your target audience for the
"supervisor-as-prompt" idea.

---

## Pre-flight checks

- [ ] Confirm you're a member of the official Anthropic Discord (check
      anthropic.com for the current invite — invites are typically
      time-limited).
- [ ] Find a `#showcase` / `#community-projects` / `#tools` channel.
      If none, pick the most-fitting general channel and don't post in
      `#general` (looks spammy).
- [ ] Read the channel pin / rules first. Some Anthropic-run servers
      explicitly disallow self-promotion outside designated channels.

## Message draft

**Length: short. Discord crowd skims; long posts get scrolled past.**

```
Hey all — released an open-source CTF batch solver this week that uses
Claude Code as the worker runtime, with a 3-layer supervision pattern
I converged on after a couple months of iteration.

The split: deterministic Python catches mechanical failures (loops,
OOM, cost overruns). A SEPARATE Claude Code session, primed with a
230-line markdown playbook, catches semantic failures (wrong direction,
hallucinated facts, partial outputs).

The "supervisor is a markdown prompt, not a Python module" design
choice is the part I'd most love feedback on from people running
agents in production.

Repo: github.com/iamkorun/hydra
Long writeup: <medium-link>

Built specifically on Claude Code primitives (ScheduleWakeup + the
jsonl event log + Bash tool); curious whether others have hit similar
shape problems and what you landed on.
```

## Reply protocol

- **Engage with technical questions** — depth of conversation is the
  point here. People in the Anthropic server are sharper than HN
  average.
- **Don't respond to "can you add OpenAI support"** in this channel —
  obvious context mismatch.
- **Do invite people to file issues** if they hit specific Hydra bugs.
- **If an Anthropic staff member engages** — respond like you'd respond
  to any community member, no special deference. They appreciate
  technical conversation, not fawning.

## What NOT to post here

- The Show HN comment text — too aggressive for this venue.
- Pure marketing ("please star").
- Any claim about Claude Code internals you're not sure about.
- Anything that crosses the "feature request" line — Anthropic staff
  who lurk the server will note it and it's not a venue for that.

## Timing

Day 2 of launch (after HN). Don't drop this during a major Anthropic
announcement (their staff are in the server too and don't want
showcase posts competing with their own announcements). If you see a
big Anthropic blog post drop, delay 1-2 days.
