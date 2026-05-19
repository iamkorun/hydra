# Newsletter outreach — specific list + pitch template

Newsletters are the highest-leverage non-launch-day channel for getting to 1k stars. A single mention in the right newsletter beats a week of HN comments. Below: targets, ordered by fit, with a pitch template per category.

---

## Target list

### Tier 1 — explicit AI/agent focus (highest fit)

| Outlet | Audience | Cadence | Why it fits |
|---|---|---|---|
| **Ben's Bites** (bensbites.com) | 100k+ AI builders | daily | Loves agent tooling; runs feature spots |
| **TLDR AI** (tldr.tech/ai) | 500k+ | daily | Curates 4-5 AI tools/papers per issue |
| **Simon Willison's Weblog** (simonwillison.net) | 50k+ | irregular | Personal blog but huge influence; Simon reads everything |
| **Latent Space** (latent.space) | 100k+ | weekly | swyx + Alessio; deep technical agent content |
| **Import AI** (jack-clark.net) | 30k+ | weekly | Jack Clark, ex-Anthropic; appreciates safety-adjacent agent work |
| **AI Tidbits** (aitidbits.substack.com) | 20k+ | weekly | Sahar Mor; loves practical tooling |

### Tier 2 — security/programming overlap

| Outlet | Audience | Cadence | Why it fits |
|---|---|---|---|
| **tl;dr sec** (tldrsec.com) | 60k+ security | weekly | Clint Gibler; explicit "tools" section every week |
| **Risky Business News** (riskybusiness.news) | smaller but very high-signal | weekly | Adam Boileau curates; CTF/sec automation fits |
| **Ruxcon's Krebs/Stahnke style sec digests** | varies | weekly | Less reliable but cheap pitches |
| **Hacker News Digest** (hndigest.com) | 30k+ | weekly | Less curatorial — picks up HN top stories. Indirect pickup if HN ranks well |

### Tier 3 — programming-general

| Outlet | Audience | Cadence | Why it fits |
|---|---|---|---|
| **TLDR Newsletter** (general) | 1M+ | daily | Hard to get in; tech feature section is gated |
| **The Pragmatic Engineer** (newsletter.pragmaticengineer.com) | 700k+ | weekly | Gergely Orosz; "developer tooling" section. Long shot but huge if it lands |
| **Console.dev** (console.dev) | 50k+ | weekly | Specifically curates dev tools. Strong fit for repo discovery |
| **CodeAcademy / Hashnode digests** | varies | weekly | Spray-and-pray category |

---

## Pitch templates

### Template A — AI/agent-focused (Tier 1)

**Subject:** `Hydra — open-source CTF solver with prompt-as-supervisor pattern`

```
Hi {{name}},

I shipped an open-source CTF batch solver last week that I think
might fit a {{outlet}} feature spot. It's a Claude Code + Docker
architecture, but the part that's gotten the most discussion is
the 3-layer agent supervision pattern — specifically the choice
to codify the LLM "judge" as a versioned markdown prompt rather
than as a Python module.

The pattern:
- Mechanical failures (loops, OOM, cost overruns) → deterministic
  Python sidecars, 0 token.
- Semantic failures (wrong direction, hallucinated facts) → a
  second LLM session running a structured playbook with a
  decision matrix.
- The "judge" lives in prompts/hydra-babysit.md, forkable for
  other domains. I shipped a bug-bounty fork using the same shape.

Repo (MIT): https://github.com/iamkorun/hydra
Long writeup: <medium link>

If this fits your readers, happy to write a one-paragraph blurb
in your house style — or you can use whatever you want from the
writeup. Either way, no pressure.

Best,
{{your name}}
```

### Template B — security/programming-overlap (Tier 2)

**Subject:** `Hydra — autonomous CTF batch solver with supervision rails`

```
Hi {{name}},

Releasing an open-source CTF batch solver this week — Claude Code
inside Docker per challenge, dispatches to 7 specialist subagents,
writes flags to a JSON. MIT license.

The interesting part isn't the solving (current LLMs are decent at
easy/medium CTF). It's the supervision stack — three layers, two
deterministic (watchdog + flag gate), one LLM (a separate Claude
session running a versioned playbook). The playbook also has a
bug-bounty variant with scope-gating, dupe detection, and rate
compliance baked into the decision matrix.

Repo: https://github.com/iamkorun/hydra
Long writeup: <medium link>

If it's a fit for {{outlet}}, ping me back — happy to provide
whatever you need.

Best,
{{your name}}
```

### Template C — programming-general (Tier 3)

**Subject:** `Open-source dev tool — autonomous CTF solver with novel agent supervision pattern`

```
Hi {{name}},

Sharing an open-source dev tool I released this week — Hydra,
an autonomous CTF batch solver written in Python, running
Claude Code agents inside Docker containers.

The design pattern I'd highlight for your readers: when you have
a long-running LLM agent doing a task, the "supervisor" that
catches it going off the rails should be a versioned markdown
prompt, not a Python module. This makes the supervisor forkable
and domain-portable. I demonstrated this by writing a bug-bounty
variant of the same playbook in an evening.

Repo (MIT, 200+ tests, CI): https://github.com/iamkorun/hydra
Writeup: <medium link>

Best,
{{your name}}
```

---

## Outreach sequencing

**Day 0 (HN drop day):** Don't outreach. Let HN run.

**Day 2 (HN-day-2):** Send Tier 1 outreach. Subject line should mention HN
front-page placement if it landed there: `(Front-paged HN yesterday) Hydra...`
— newsletter editors triage by traffic signal.

**Day 4:** Send Tier 2 outreach.

**Day 7:** Send Tier 3.

**Don't:**

- Outreach before the HN drop. You burn the asset.
- Send mass-personalized emails (`Hi $NAME`) — looks like a mail merge.
- Follow up more than once. If they don't reply in 5 days, they passed.
- Ask for "links" or "favors." Pitch the content, let them decide.

---

## Specific people to email (verify contact info before sending)

| Name | Outlet | Contact |
|---|---|---|
| Simon Willison | simonwillison.net | swillison@gmail.com (publicly listed) |
| swyx | latent.space | swyx@latent.space |
| Clint Gibler | tl;dr sec | tldrsec.com has a contact form |
| Sahar Mor | AI Tidbits | sahar@aitidbits.com |
| Gergely Orosz | Pragmatic Engineer | gergely@pragmaticengineer.com |
| Jack Clark | Import AI | jack@jack-clark.net (best-effort guess; check Substack) |

Don't include this list in any public artifact — it's for the operator's outreach folder only.

---

## What to track

For each outreach:

| Date | Outlet | Contact | Sent | Response | Featured? |

If featured: thank the editor publicly + amplify their newsletter on socials. Reciprocity is the long-game currency in this space.

If ignored: don't take it personally. Newsletter editors get 100+ pitches a week. Move on.
