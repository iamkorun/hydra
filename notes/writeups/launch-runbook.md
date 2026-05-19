# Launch runbook — day-by-day execution

Single source of truth for the launch. Check off as you go. Everything an autonomous lead can't do without you (posting to platforms, replying to comments, deciding tone) is here as a step.

---

## Pre-launch checklist (Day 0)

- [ ] Read `flagship-supervision.md` end-to-end. Edit voice/tone to feel like *you*. Add a 1-sentence "I'm X, I work on Y" intro if you want personal credibility (optional but helps Medium).
- [ ] Publish flagship to Medium. **Save the URL.**
- [ ] Find/replace `<medium link>` placeholder across all other drafts:
  - `notes/writeups/show-hn.md`
  - `notes/writeups/x-thread.md`
  - `notes/writeups/reddit-posts.md`
  - `notes/writeups/dev-to-and-linkedin.md`
  - `notes/writeups/newsletter-outreach.md`
- [ ] Crosspost flagship to Dev.to with the canonical URL set to Medium. (See `dev-to-and-linkedin.md`.)
- [ ] Confirm GitHub Actions CI is green at https://github.com/iamkorun/hydra/actions
- [ ] Confirm README renders correctly on github.com (ASCII diagram, badges, links).
- [ ] Sanity-check: `git clone` the repo into a fresh directory and run `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest -q` — should pass clean from scratch.
- [ ] Optional but high-leverage: ask 5-10 trusted dev friends to **star the repo before launch.** The "not 0 stars" signal matters on HN. Don't ask them to upvote HN — that's vote manipulation.

---

## Day 1 — HN drop (Tuesday, 8:00am US Pacific = 11am US Eastern = 22:00 BKK)

The single highest-leverage 4 hours of the entire campaign. Timing is non-negotiable.

- [ ] **08:00 PT** — Submit to HN. Use the title from `show-hn.md`. URL = `https://github.com/iamkorun/hydra`. Don't link Medium as the URL (HN guidelines prefer source).
- [ ] **08:01 PT** — Post the first comment from `show-hn.md` as a reply to your own submission. This becomes the de-facto description for HN browsers.
- [ ] **08:05 PT** — Post X thread from `x-thread.md`. Pin it to your profile. Include the HN link in the last tweet.
- [ ] **08:10 PT** — Light socials (Mastodon, Bluesky if you use them).
- [ ] **08:30 PT onwards** — Reply to HN comments. Aim for ~1 reply per 10-15 minutes, not faster (looks bot-like). Use reply playbook in `show-hn.md` for common questions. **For 8 hours straight.** This is the work.
- [ ] **12:00 PT (lunch)** — Check HN rank. If it's on front page (top 30), STOP outreach and focus on comment replies. If it's stuck in `/new`, post on Reddit r/netsec to send a small traffic blip (HN's ranking weighs external signals).
- [ ] **16:00 PT** — Reddit r/LocalLLaMA post (separate variant from r/netsec — see `reddit-posts.md`).
- [ ] **20:00 PT** — Take a break. Don't reply to comments tired; you'll write something you regret.

---

## Day 2 — Compound

The HN long-tail is +2-5 days. Most of your stars from HN come AFTER day 1.

- [ ] Reply to overnight HN comments (US/EU/Asia all had a chance to read by now).
- [ ] r/MachineLearning discussion post (variant in `reddit-posts.md`).
- [ ] Anthropic Discord: post in `#showcase` channel if it exists, or the most fitting general channel. Brief: 2-3 sentence intro + repo link + Medium link. Don't shill in non-showcase channels.
- [ ] **Newsletter outreach Tier 1.** Use templates in `newsletter-outreach.md`. If HN front-paged yesterday, put `(Front-paged HN)` in the subject line.
- [ ] LinkedIn post from `dev-to-and-linkedin.md`.

---

## Day 3 — r/securityCTF + outreach Tier 2

- [ ] Reply to remaining HN comments.
- [ ] r/securityCTF post (variant in `reddit-posts.md`).
- [ ] **Newsletter outreach Tier 2.**
- [ ] Check star count. If <100, time to re-examine framing. If 100-300, on track. If 300+, you're in good shape.

---

## Day 4-6 — Drip & engage

- [ ] Daily: reply to issues/PRs that come in. Even bad ones — show responsiveness.
- [ ] Daily: skim X mentions, RT/quote any interesting commentary.
- [ ] Day 5: **Publish Article #2** (`notes/writeups/article-2-prompt-supervisor.md`) on Medium. Don't re-cross-link the flagship in the body — let it stand on its own.
- [ ] Post Article #2 link on X with a 3-tweet teaser, not a full thread (the long thread already happened).
- [ ] Day 7: **Newsletter outreach Tier 3.**

---

## Day 7-14 — Maintenance + Article #3

- [ ] Continue: weekly star count check. Trend matters more than absolute.
- [ ] Continue: reply to issues within 24h.
- [ ] Day 13-14: **Publish Article #3** (`notes/writeups/article-3-cache-cadence.md`) — technical deep-dive, smaller audience, but durable SEO value.

---

## Post-day-14 — Long game

Stars after week 2 come from:

1. **Continued content** — 1 article/week minimum. Topics: a benchmark run, a war story from running Hydra against a public CTF, a deep-dive on one specialist subagent.
2. **GitHub Trending pickup** — if you cross ~200 stars in a week, you may trend in the `python` or `artificial-intelligence` tags. Trending compounds.
3. **Conference / podcast** — pitch one. "Latent Space" podcast, "Changelog", "Self-hosted" — any one of these can move the needle by 200-500 stars.
4. **Real benchmark numbers** — once you have published numbers on a public corpus (InterCode-CTF is the obvious choice), publish a third Medium post with the numbers. Benchmarks travel.

---

## Anti-checklist (don't do)

- [ ] DON'T buy stars/upvotes. GitHub removes them and shadow-bans the repo. HN bans accounts permanently.
- [ ] DON'T ask in DMs "can you star my repo." Looks desperate, doesn't work.
- [ ] DON'T argue with HN trolls. Reply once, factually, then ignore.
- [ ] DON'T post the same text on every platform. Each platform's audience differs. The variants in this folder exist for a reason.
- [ ] DON'T launch on Friday/Saturday. US tech crowd is offline. Tuesday morning is best.
- [ ] DON'T post during major news cycles. Election day, big Apple event, big Anthropic/OpenAI announcement — your repo gets buried.

---

## Decision delegations

You have authority here. The lead's pre-decided choices, in case you forget:

1. **Position:** CTF tool *framed as* agent supervision case study.
2. **Hero angle:** "The supervisor is a prompt."
3. **Channel order:** Medium → HN → X → Reddit → Dev.to → Anthropic Discord → newsletters.
4. **HN timing:** Tuesday 8am PT.
5. **Don't claim benchmarks you don't have.** "Watch this space" beats "made-up percent."
6. **If overwhelmed:** drop LinkedIn and Tier 3 newsletter outreach. Both are low-leverage.

---

## Success metrics

| Milestone | Target |
|---|---|
| HN front page (top 30) | Day 1 |
| 100 stars | Day 3 |
| 300 stars | Day 14 |
| 1000 stars | Month 3 |
| First external blog post about Hydra | Month 1 |
| First contribution PR | Month 1 |
| First fork of `bb-babysit.md` for a new domain | Month 2 |

If you miss the HN front page — don't despair. Most repos that hit 1k stars don't front-page on first try. Continue the drip-feed strategy and aim for a second HN run in 2-3 months with new content angle (benchmark results, war story, v2 announcement).
