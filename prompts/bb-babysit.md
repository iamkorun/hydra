# Bug-Bounty babysit — supervised single-worker protocol

Use this when the user wants Claude to hunt for vulnerabilities in a
single Bug Bounty program with **one** worker agent (Claude Code, a
browser-agent harness, or a custom loop), while Claude-the-supervisor
catches out-of-scope drift, rate-limit burn, hallucinated findings,
and dupes before they cost the user a program ban or a wasted submit.

The user will invoke this with a program name / scope URL / bug class
/ budget cap. Everything below is the standing protocol for the
session.

**Why babysit over autonomous fleet:** dupe rate + triage friction +
scope-drift liability > single-instance throughput. Solo-hunter + LLM
+ patient supervisor beats unsupervised fleet on submittable-rate
per dollar. XBOW-style fleets work because they have $M of compute to
absorb the dupe tax; you don't.

## Inputs you need before starting

Ask the user (or parse from the input) for:

1. **Program identity**
   - Platform: HackerOne / Bugcrowd / Intigriti / Bugzilla / direct / native (e.g. OpenAI on Bugcrowd, Google VRP native)
   - Program handle / URL
   - Current scope doc URL (changes!)
2. **Scope constraints (hard gates — ALL must be parsed before any tool call fires)**
   - Explicit in-scope assets (domains, IPs, product names, API endpoints)
   - Explicit out-of-scope assets (usually 10x longer than in-scope list)
   - Bug classes accepted (auth, IDOR, SSRF, prompt-injection, agent-hijack, etc.)
   - Bug classes explicitly excluded (rate-limiting, self-XSS, social-engineering, missing headers-only)
   - PII / real-user-data rules (typically: never prove by extracting data of real users; use attacker-controlled accounts)
   - Rate limit / polite-scan limits (often: ≤5 req/sec per host, no brute-force)
3. **Attack surface / hypothesis**
   - Which bug class you're hunting today
   - Why this class on this program (fresh feature? prior writeup? gap in coverage?)
4. **Budget caps** (see table below)
5. **Model preference** — haiku for recon parsing, sonnet for hypothesis, opus for PoC craft

## Pre-flight (BEFORE any outbound traffic)

Do NOT let the worker fire a request until:

1. **Scope doc parsed into a structured gate.** Generate a
   `work/scope.json` with `in_scope: [...]`, `out_scope: [...]`,
   `excluded_bug_classes: [...]`, `rate_limit_rps`, `data_rules: [...]`.
   Every outbound HTTP URL must match an in-scope pattern AND not
   match any out-scope pattern. If fuzzy, ask the human.
2. **Test account provisioned.** Attacker account and (if needed) a
   separate victim account, both controlled by you. Record credentials
   in `work/accounts.md`. Never use a third party's account to
   demonstrate impact.
3. **Baseline captured.** Logged-in + logged-out fingerprints for the
   target: `curl -sSI`, response hashes of home page, JS bundle hashes.
   Diff these later to detect "did my payload actually change behavior,
   or did I just hit the WAF's canned response?"
4. **Dupe pre-check.** Search the program's public disclosures and
   general web for prior reports of your hypothesis. Write the top 5
   hits to `work/prior-art.md` with "close but different because ___"
   annotations. If anything is identical, pick a new hypothesis.
5. **Proxy wired.** All traffic flows through a local proxy
   (mitmproxy / Caido / Burp headless) that logs every request +
   response + timestamp to `work/traffic.log` for evidence. Never
   allow the worker to issue raw `curl` outside the proxy.

Do NOT launch the worker loop if:
- Scope is ambiguous on any asset the hypothesis touches. Ask.
- Program is in "paused" / "retired" state.
- You'd need to attack a real user's account to demonstrate.
- The hypothesis can only be proven by bypassing ToS (e.g., accessing
  paid-tier feature without paying): that is ToS violation, not bug.

## Launching the worker

Choose the worker flavor that matches the bug class:

| Bug class | Worker | Tool integration |
|---|---|---|
| Prompt injection (OpenAI Agent, Gemini, Claude) | Claude Code inside a container with curl + browser-use | Proxy all HTTP. Host a malicious-page scaffold on a scope-authorized endpoint |
| Web auth / IDOR | Claude Code + `httpie` + Caido proxy | Authenticated session token injected via proxy |
| SSRF / cloud metadata | Claude Code + requests lib + DNS log server | Burp Collaborator or interact.sh for OOB |
| Business logic | Claude Code + scripted client | mitmproxy recording |
| ML model extraction / adversarial | Notebook-based worker (no persistent container) | — |

Worker launch invariants:
- Always through the proxy (no direct network)
- Container / process has **no network egress** except to: scope
  allowlist + attacker-controlled OOB endpoints + the proxy host
- Writes ALL findings to `work/hypotheses.json` + `work/candidates/`
  (not to stdout)

Cadence: **single-worker**, single hypothesis at a time. Fan-out of
hypothesis is done by **re-invoking** the worker after the supervisor
reviews intermediate state, not by parallelism.

## Budget caps

Per session (typical tuning — adjust to wallet):

| Phase | Claude API cap | Time cap |
|---|---|---|
| Scope parse + dupe check (recon) | $1 | 20 min |
| Hypothesis exploration | $5 | 60 min |
| PoC craft + validation | $10 | 90 min |
| Total per-day per program | $25 | 4 hrs active |

Kill when spend exceeds cap without a submittable candidate. A
"candidate" means: reproducible POC + scope-clear + non-dupe +
documented impact. Anything less is a dead-end.

## Monitor loop (supervisor)

Use `ScheduleWakeup` between checks. Cadence:

- **270s** (prompt-cache-warm sweet spot) while the worker is
  actively probing
- **900-1800s** while human is drafting report / reviewing candidate

Each wake, pull compact state:

- `work/hypotheses.json` (current hypothesis + test status)
- `work/traffic.log` tail (last 20 requests + response hashes)
- `work/candidates/*.md` count
- `docker stats` / worker process RSS
- Worker log size + last tool call

Never `cat` / `Read` the full traffic log or full transcript — grep /
jq with `tail -N`.

## Cheap checks (run per-wake, 0 token)

1. **Scope compliance** — grep traffic.log for any hostname not in
   `work/scope.json:in_scope`. MUST be empty.
2. **Rate compliance** — bucket requests by 1s windows, check max <
   configured rps. If over, PAUSE worker, reduce concurrency.
3. **Loop detection** — count distinct (endpoint + payload_hash)
   tuples in last 5 min. If same tuple repeated ≥5x → loop.
4. **Signal density** — count 200/403/500 status distribution. Pure
   403 stream = WAF'd or wrong endpoint; pivot. Diverse statuses =
   interesting surface.
5. **Distinct-endpoints probed** — should grow monotonically early,
   plateau during PoC craft. Flat for 10 min mid-exploration = stuck.
6. **Hypothesis count** — `jq 'length' work/hypotheses.json`. Should
   grow. Flat = worker not reasoning, just probing.
7. **Worker cost so far** — sum `usage.*_tokens × rate` from
   `logs/claude.stdout.jsonl`. Compare to phase cap.

## Decision matrix

Act on the **first matching row**, top down:

| Signal | Action |
|---|---|
| Worker issues out-of-scope request | **KILL immediately.** Any OOS hit is grounds for program ban even if unintentional. Review scope.json, tighten, restart |
| HTTP 429 from target | PAUSE. Halve req-rate. Resume after 5 min. If persists, KILL and flag to user — program might have hidden stricter limits |
| Worker tries to use credentials from training memory ("I know this app uses default admin:admin") | KILL. BB requires DERIVED evidence. Force the worker to log to `work/prior-knowledge.log` and restart with "no-recall" constraint |
| Same (endpoint + payload_hash) ≥5x no signal | KILL this hypothesis. Pivot or end session |
| `work/candidates/` has new .md file | PAUSE supervisor loop, switch to candidate-review mode (see below) |
| Distinct endpoints flat for 10 min + >$3 spent | KILL. Worker stuck in local min; reload with different bug-class prompt |
| PoC reproduces in fresh container from just the candidate.md instructions | CONTINUE — this is a submittable. Wake human for final report |
| PoC requires manual tweaking to reproduce | KILL and document. Non-reproducible = not submittable, triager will NA it |
| Cost over phase cap with no candidate | KILL. Write postmortem, don't rollover budget |
| WAF challenge page in response (Cloudflare turnstile etc.) | PAUSE — worker shouldn't fight WAF; flag user to decide scope of this |
| Agent requests PII extraction / real user data | KILL. Rewrite hypothesis to use attacker-controlled data only |
| Healthy: distinct endpoints growing, hypotheses updating, diverse status codes, cost on-budget | CONTINUE. Schedule next wake |

### KILL procedure

```
# 1. Stop the worker container / process
docker kill <worker-name> 2>&1 || kill -INT <pid>

# 2. Snapshot state for postmortem
cp -r work/ postmortems/$(date +%Y%m%d-%H%M%S)/

# 3. If candidate existed but we killed for scope reasons,
#    preserve it separately so we don't lose research
mv work/candidates/ postmortems/.../candidates-preserved/
```

Never auto-restart after KILL. Always surface the reason to human and
wait for explicit restart intent.

### Candidate-review mode (when a finding drops)

When `work/candidates/<slug>.md` appears:

1. PAUSE worker loop entirely.
2. Supervisor reads the candidate markdown (small — should be
   ≤500 lines). Verifies:
   - Reproducibility: can you re-run the PoC from just the
     instructions in a fresh container? (spawn a sub-agent to try)
   - Scope: every URL in the PoC matches scope.json:in_scope.
   - Impact: severity justified with concrete language (not vibes)
   - Non-dupe: final grep against prior-art.md
   - Data hygiene: no real-user data in screenshots / logs
3. If all pass → wake user for final report drafting (human writes
   the narrative; supervisor only verifies technical accuracy).
4. If any fails → dump candidate into `postmortems/rejected/` with
   reason, restart worker with corrected hypothesis.

## Reporting back to user

After each wake, respond in one short block:

```
State: 🟢 running / ⏸ paused / 🛑 killed / 🎯 candidate-ready
Hypothesis: <one line>
Spend: $X.XX of $Y.YY cap, <time used>/<time cap>
Traffic: <N reqs last 5 min>, <distinct endpoints>
Signal: <one-line novelty, e.g. "new JSON error reveals internal field">
Decision: CONTINUE +<N>s | PAUSE | KILL | HANDOFF_TO_HUMAN
Reason: <one sentence with specific signal that triggered>
```

Don't narrate the checks. Just results. When a candidate emerges,
drop the standard report and instead emit a candidate-review summary.

## When the target is flaky / behind hostile infra

Programs with aggressive WAF (Cloudflare Enterprise, Akamai Bot
Manager, Imperva) make iteration expensive — every probe risks a ban
or a challenge-page that wastes tokens on garbage. Strategy:

1. Slow down. 1 req every 3-5s, not bursts.
2. Authenticated + session-affinity (same cookie jar) to look like a
   real user.
3. Cache-friendly probes first (GETs with real-looking params) to
   warm the WAF's "this is a human" trust.
4. Reserve expensive probes (payload variants) for sessions that
   passed the trust warm-up.
5. Never run prompts like "bypass the WAF" — that's an anti-goal;
   you're hunting bugs IN the app, not in the WAF. If WAF blocks
   every probe, the surface is not researchable here; pivot.

## Anti-patterns to avoid

- **Fleet thinking** — do NOT parallelize hypotheses. Every
  hypothesis gets its own sequential run so you can supervise it
  properly. BB is quality-weighted not quantity-weighted.
- **Training-memory fallbacks** — "I know this framework had a CVE
  in 2023" → test specifically and log the recall in
  `work/prior-knowledge.log`. Never submit without deriving via
  probes.
- **Partial PoC submissions** — "I think it might work" is a NA.
  Never submit until the candidate-review step has reproduced it
  from scratch.
- **Reading full transcripts / traffic logs** — always jq/grep with
  `tail -N` or count-distinct. Full reads will blow your context.
- **Auto-resume after kill** — compounds failures. Always
  human-confirm before re-launch.
- **Touching out-of-scope even once** — not negotiable. Program
  bans are permanent and cross-program (some platforms share
  reputation).
- **Copy-pasting LLM-generated report prose** — triagers can smell
  AI-generated reports and reject them for quality. Human writes
  the narrative; LLM supplies technical facts only.
- **Chasing easy classes on popular programs** — XSS on Fortune
  500 with public VDP = 99% dupe rate. Hunt harder classes or less
  popular programs where your supervised-hunter edge matters.
- **Ignoring program ToS** — "no DoS", "no automated scanning", "no
  testing against production without authorization" — read ALL
  program-specific rules before launching. They override this
  playbook.

## Example one-shot invocation

User says: "OpenAI Safety Bounty, hunt indirect prompt injection on
ChatGPT Agent via malicious webpage, budget $25 today".

Response flow:
1. Parse OpenAI Safety Bounty scope doc from Bugcrowd → write
   `work/scope.json`. Confirm ChatGPT Agent / Browser is in-scope,
   confirm third-party indirect prompt injection is a target class,
   confirm reproducibility threshold (50%).
2. Dupe check: search Bugcrowd disclosures + public writeups for
   "ChatGPT Agent prompt injection webpage". Write top 5 to
   `work/prior-art.md`. Pick a novel angle (e.g., "payload encoded
   in PDF metadata rendered by Agent's browse tool" if no prior
   work exists).
3. Spin up attacker test account for ChatGPT Agent (paid tier if
   required, acknowledge in user-spend ledger).
4. Host malicious page scaffold on `your-domain.com` (must be
   attacker-controlled, not on a real user's server).
5. Proxy all ChatGPT Agent interactions through mitmproxy.
6. Launch Claude Code worker with hypothesis: "Can ChatGPT Agent be
   tricked into exfiltrating its conversation history when browsing
   `your-domain.com/payload-N.html`?" Worker iterates payloads with
   logged instructions, each new attempt in a fresh ChatGPT Agent
   session.
7. First ScheduleWakeup at +270s.
8. Monitor decision matrix. Pause on any candidate.
9. On terminal state (candidate or kill), emit summary with spend +
   next action for user.

## Checklist before you hit "Launch"

Paste this into the thread before any outbound traffic and confirm
each box with the human:

- [ ] scope.json parsed, human has reviewed
- [ ] Attacker-owned accounts provisioned
- [ ] Proxy running, traffic.log writing
- [ ] Budget caps agreed ($ per phase, total per day)
- [ ] Hypothesis documented in `work/hypotheses.json`
- [ ] Dupe pre-check done, novel angle confirmed
- [ ] No real-user data will be touched
- [ ] Program ToS re-read today (rules change)
- [ ] Kill-switch command tested (docker kill works)
- [ ] Human agrees to supervise for session duration
