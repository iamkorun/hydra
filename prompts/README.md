# Prompts — operator playbooks

The supervisor in Hydra's 3-layer architecture is a **prompt**, not a
Python module (see [README — Supervision](../README.md#supervision)
for the rationale). This directory collects those prompts, one per
domain.

## Available playbooks

| File | Domain | Workers | Worker runtime |
|---|---|---|---|
| [`hydra-babysit.md`](hydra-babysit.md) | CTF batch solving | N parallel | Hydra (this repo) |
| [`bb-babysit.md`](bb-babysit.md) | Bug-bounty hunting | 1 supervised | Claude Code with proxy |
| [`ctf-ingest.md`](ctf-ingest.md) | Importing CTF challenge metadata into `challenges.json` | — (data prep) | — |

## How to use a playbook

1. Open a separate Claude Code session (the *supervisor* — distinct from
   the worker / Hydra batch you'll launch).
2. Paste the entire contents of the relevant playbook into that session.
3. Tell the supervisor what you want to monitor (challenges JSON path,
   target endpoints, budget caps).
4. The supervisor uses `ScheduleWakeup` to wake every ~270s, runs `jq`
   / `tail` / `stat` against the worker's log, and applies the decision
   matrix in the playbook.
5. When the supervisor reports a terminal state (DONE, KILL, PAUSE,
   HANDOFF_TO_HUMAN), respond per the playbook's reporting protocol.

## How to fork a playbook for a new domain

1. Copy `hydra-babysit.md` or `bb-babysit.md` to
   `prompts/<your-domain>-babysit.md`.
2. Replace the **Inputs you need before starting** section with your
   domain's questions.
3. Rewrite **Pre-flight verification** with your domain's targets
   (HTTP handshake? Database connection? K8s pod ready? S3 bucket
   policy?).
4. Rewrite the **Decision matrix** rows. This is the bulk of the
   work — every row maps a signal to an action and should be
   defensible to a skeptic.
5. Test by running it against simulated failure modes.

If you build a playbook for a domain that interests you, please
[open an issue](https://github.com/iamkorun/hydra/issues/new?template=playbook_fork.md)
— this directory is meant to be a catalog of supervision patterns
across domains.

## Why one prompt per domain, not one parameterized prompt

Tried both during development. Parameterized prompts grow into
giant if-cases ("if domain == ctf, then... else if domain == bb,
then..."). The decision matrix is too domain-specific to share —
the row "Banner of wrong challenge → PAUSE" makes no sense in
bug-bounty land, and "Worker issues out-of-scope request → KILL"
makes no sense for CTF.

Forks are cheaper than abstractions when the domains are
qualitatively different.
