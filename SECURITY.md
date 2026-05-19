# Security Policy

## Scope

Hydra is a security research tool — its purpose is to dispatch agents
that exploit intentionally-vulnerable CTF challenges. Treat its output
as research, not production data.

**Run Hydra against:**
- CTF platforms (HackTheBox, picoCTF, TryHackMe, custom CTFs) where
  you have explicit permission.
- Targets you own or have written authorization to test.

**Do NOT run Hydra against:**
- Production systems without explicit written authorization.
- Bug-bounty programs without first reading the program scope (use
  [`prompts/bb-babysit.md`](prompts/bb-babysit.md) — it has scope
  gating baked in).
- Third-party systems where you do not have testing rights.

You are responsible for the legality of what you point Hydra at.

## Reporting a security issue in Hydra itself

If you find a vulnerability in Hydra (the orchestrator, watchdog,
flag gate, Docker setup, etc.) — *not* in challenges Hydra solves —
please open a GitHub issue with the `security` label, or contact the
maintainer privately via GitHub.

Please do **not** report:
- Vulnerabilities in challenges Hydra has solved (that's the point).
- Issues with Claude Code itself — those go to Anthropic.
- Generic "AI agents can be jailbroken" reports — known and out of
  scope for this project.

## Hardening notes

- Workers run as root inside their Docker container. The container
  has no host network access by default; bind-mounts are read-only
  except for `runs/<name>/`.
- The container has internet egress (needed for `apt`, `pip`,
  `curl`) and write access to its own workdir. If you're solving
  challenges that should NOT have egress, override `--network none`
  via the Docker run flags in your fork.
- Claude Code credentials are bind-mounted read-only at
  `/root/.claude-host`, then copied to a writable `/root/.claude`
  inside the container so the worker can write session state. If
  your `~/.claude/` contains keys for unrelated projects, consider
  using `--credentials-dir` to point at a scoped credential dir.
- The `cost_cap` watchdog signal caps token spend per challenge but
  trusts Hydra's local accounting — your Anthropic-side billing is
  the source of truth.
