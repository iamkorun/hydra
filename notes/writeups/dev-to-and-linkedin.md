# Dev.to crosspost + LinkedIn post

Lower-leverage channels than HN/Medium/X but cheap to post once content exists.

---

## Dev.to crosspost

Dev.to is friendlier than HN — fewer "this is just a wrapper" comments, more "thanks for sharing." Crosspost the flagship article with minor tone adjustments. Add the Dev.to-specific canonical-URL header pointing back to Medium so SEO doesn't split.

**Frontmatter:**

```yaml
---
title: "The supervisor is a prompt: a 3-layer pattern for keeping LLM agents on-track"
published: true
description: "After building an autonomous CTF batch solver, I converged on a 3-layer supervision pattern where the LLM judge is a versioned markdown prompt, not a Python module. Here's why."
tags: ai, llm, opensource, security
canonical_url: https://medium.com/@iamkorun/...
cover_image: <generated or skipped>
---
```

**Tone adjustments from Medium version:**

- Drop "I" voice slightly — Dev.to readers skim more, prefer headings-as-summary
- Add 1 more code block — Dev.to renders code well, breaks up text
- Shorter paragraphs (Dev.to is mobile-skewed)
- Same content, just denser whitespace

**Don't:**

- Add a "Follow me for more" CTA — Dev.to community is allergic to it
- Cross-post the Show HN comment text (too aggressive for this venue)
- Tag with #beginners (we're not)

---

## LinkedIn post

LinkedIn is the lowest-leverage channel for this kind of project — corporate audience, less tolerant of technical depth, but very tolerant of "thought leadership" framing. Useful if you want recruiters / VCs / non-technical leadership to see this exists.

**Post (~250 words, single block, no hashtags at end):**

```
Spent the last two months building an autonomous CTF batch solver
called Hydra. JSON of challenges in, JSON of flags out.

The hard part wasn't building the solver. It was figuring out how
to keep the LLM agent from going off the rails for the full
60-minute timeout while I'm not watching.

What I converged on is a 3-layer supervision pattern that I think
generalizes well beyond CTF — to any long-running agent task
where you want to walk away and come back to working output.

Layer 1: A second LLM session, primed with a versioned markdown
playbook, monitors the worker every ~270 seconds and applies a
decision matrix (continue, kill, upgrade, pause).

Layer 2: Deterministic Python sidecars catch mechanical failures
(loops, OOM, cost overruns) without spending tokens on supervision.

Layer 3: Output validators reject malformed results before they
reach the final artifact.

The design choice that gets the most pushback in DMs: Layer 1's
supervisor is a markdown file, not a Python module. Same reason
you'd put your API spec in OpenAPI instead of in code comments —
the artifact deserves first-class status.

Hydra is MIT-licensed. The supervision playbook is forkable for
other domains; I've already built a bug-bounty variant using the
same shape.

Repo: https://github.com/iamkorun/hydra
Writeup: <medium link>

If you're working on LLM agent supervision in production, I'd
love to compare notes.
```

**Targeting:**

- Post from your main LinkedIn account
- Don't use 30 hashtags — LinkedIn's algorithm punishes that since ~2024
- Best time: Tuesday-Thursday, 8-10am local time (when corporate scrolls between meetings)
- DON'T tag specific companies / executives — looks desperate, gets buried by algorithm
- DO accept connection requests from people who engage; that's where the long tail of value lives

---

## Mastodon / Bluesky (optional)

If you're active on either:

**Mastodon** (#AI / #InfoSec / #OpenSource crowd, very picky about boost-bait):
> Built an autonomous CTF batch solver with a 3-layer supervision stack: deterministic watchdog + LLM-prompt-as-judge + output validators. The LLM judge is a markdown file you paste into a separate Claude Code session, not a Python module — making it forkable and domain-portable. MIT.
> 
> https://github.com/iamkorun/hydra

**Bluesky** (more conversational, smaller infosec community):
> Quick share: spent 2 months on this and the architecture insight that stuck — your LLM agent's supervisor should be a prompt, not a Python module. Hydra (MIT) ships a versioned 230-line markdown playbook that monitors a worker batch via ScheduleWakeup + jq. Forkable for any domain.
> 
> https://github.com/iamkorun/hydra

Both: post once, don't beg for boosts/reposts, reply to engagement, let it ride.
