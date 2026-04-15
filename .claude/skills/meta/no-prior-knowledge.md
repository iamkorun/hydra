# No prior knowledge — derive, don't recall

**Rule:** a CTF solve must be produced by *running code against the challenge*. Training memory (default credentials, canonical answers for well-known rooms, "I remember this room is Simple CTF") is not evidence.

## The failure pattern this prevents

> Exploit doesn't fire → "I know this is TryHackMe Simple CTF, the creds are `mitch:secret`" → SSH in with recalled creds → get the flag → submit

The flag matches, the run is logged green, but the agent didn't *solve* anything. Scale this to a competition where challenge authors rename users or patch versions and the solve rate collapses.

This also bypasses the verifier: the verifier sees `mitch@box:~$ cat user.txt` producing the right string — provenance looks strong. It can't tell that the `mitch:secret` step was fabricated.

## When you're tempted to use prior knowledge

Typical triggers:
- "This looks like <well-known room/challenge>; the answer is ..."
- "Default creds for <product> are <u>:<p>"
- "CVE-XXXX exploit always yields creds `admin:admin`"
- "The flag format for this competition is always <X>"

All of these are **hypotheses**, not answers. Treat them the same as any other hypothesis: verify with a command.

## Mandatory protocol

### 1. Prefer derivation. Always.

If you have time/tool budget, derive the value from the challenge:

- Creds from SQLi → crack hash, not "it's probably `admin`"
- Version from CMS → check `CHANGELOG.txt`, not "it's probably 2.2.8 because that's the vulnerable one"
- Flag format → check one example in the competition, not "pico uses picoCTF{...}"

### 2. If you must use prior knowledge, audit-log it

Before you act on the recalled value, append to `./work/prior-knowledge.log`:

```
timestamp: 2026-04-15T12:25:00Z
phase: credential-recovery
derivation-attempted: CVE-2019-9053 time-based SQLi against m1_idlist (3 payload variants)
derivation-result: payload reached server (diagnostic 2 passed) but SLEEP(5) did not delay (diagnostic 5 failed); target appears patched or vector is different
prior-knowledge-used: username=mitch, password=secret (recalled from TryHackMe "Simple CTF" room notes)
risk: if this challenge is a clone/modified version, creds will be wrong and downstream flag will be wrong
verification: will attempt SSH login; if it fails, fall back to continuing derivation
```

The log is **required** before committing to a prior-knowledge step. No log → you're not allowed to take the shortcut.

### 3. Verify the prior knowledge matches the environment

Before you rely on it downstream:

```bash
# Don't just try the creds — also check they're *this* environment's creds
ssh -o BatchMode=yes -o ConnectTimeout=5 mitch@target 'id; hostname; cat /etc/os-release | head -2'
```

If it works: you got lucky, the environment matches. If it fails: the recall was wrong, continue deriving.

### 4. After success, finish the audit

When the run completes, append the outcome to the log:

```
outcome: prior knowledge was correct (mitch:secret worked) — but this means the
         CVE exploit did not fire; underlying exploitation capability is unverified.
                  followup: investigate why time-based SQLi didn't trigger (see ./work/exploit-debug.md)
```

## How the verifier uses this

If `./work/prior-knowledge.log` exists when the verifier is invoked, the candidate is automatically tagged `SUSPECT` with reason "solution includes non-derived step". The triage agent decides whether to accept or re-dispatch with "derive the skipped step".

**Consequence:** if you skip the log to "look clean", you've fabricated the solution. The verifier won't catch you this time; next time, with a variant challenge, the fabricated step will produce a wrong flag and you'll burn the whole run.

## Exceptions (when prior knowledge is fine without logging)

- **Tool invocations** — knowing the flag for `binwalk -e` is training knowledge; that's tool use, not a CTF answer.
- **Protocol facts** — "HTTP 302 redirects" is training knowledge; not an answer.
- **Flag format contracts** — the README states `picoCTF{...}`; using that is following instructions, not recall.

The rule is specifically about **challenge-specific answers** (creds, paths, flag bodies, config values tied to the target) being imported from training instead of being extracted from the target.
