# Hydra babysit — run background + monitor protocol

Use this when the user wants Claude to run a hydra batch in the background and
manage it autonomously: catch hallucination loops, upgrade models on skill
ceiling, pause on infrastructure flaps, and stop before partial/wrong flags
pollute `flags.json`. Goal: solve with minimum token burn, never silently
record a bad flag.

The user will paste or invoke this with a target JSON (e.g. `batch.json`,
`phase-1.json`) and possibly per-stage IPs. Treat everything below as the
standing protocol for the session.

## Inputs you need before starting

Ask the user (or confirm from the input file) for:

1. **Challenges JSON path** — the file hydra consumes (`./path/to/X.json`).
2. **Target endpoints** — IP(s) and port(s) per challenge that needs a
   remote. "Same IP reused across stages" is common on platforms that
   recycle IPs per machine deploy.
3. **Model preference** — default `claude-sonnet-4-6` for Easy, upgrade to
   `claude-opus-4-7` for Hard or after sonnet spins.
4. **TTL hint** — some platforms expire containers after ~20–30 min. Ask
   if unknown; plan kill-and-redeploy around it.

## Pre-flight (before `hydra` starts)

Never start hydra until the target is **verified responsive**. For each
challenge with a remote:

| Service | Verification one-liner |
|---|---|
| HTTP / HTTPS | `curl -s -o /dev/null -w "%{http_code}\n" http://IP:PORT/ -m 5` |
| TCP banner (nc) | `timeout 3 nc IP PORT -w 3 </dev/null \| head -3` |
| Modbus/TCP 5020 | `printf '\x00\x01\x00\x00\x00\x06\x01\x01\x00\x00\x00\x03' \| nc -w3 IP 5020 \| xxd` |
| BACnet/IP 47808 UDP | `python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.settimeout(3);s.sendto(bytes.fromhex('810a001101040005010c0c02000082194d'),('IP',47808));print(s.recvfrom(2048))"` |
| EtherNet/IP 44818 | `python3 -c "import socket,struct;s=socket.socket();s.settimeout(5);s.connect(('IP',44818));s.send(struct.pack('<HHLL8sL',0x0063,0,0,0,b'\0'*8,0));print(s.recv(1024).hex())"` |
| Raw nmap | `nmap -Pn -p- --min-rate 5000 --open IP \| tail -10` |

Important: verify **the service-specific handshake**, not just "port is
open". On DropCTF-style platforms one IP can serve the wrong challenge —
probe the banner/protocol to confirm it's the expected machine.

Also defend against **IP recycling**: an IP that ran challenge A an hour
ago may now serve challenge B. If the banner does not match the challenge
description (e.g. "Uncle Somchai Encryption Booth" when you expected
Modbus), stop and ask the user which machine they actually deployed.

Do NOT launch hydra if:
- Ping works but no expected port is open (machine warming up).
- Handshake returns wrong protocol banner.
- `No route to host` (machine not online yet).

Wait and re-probe, or ask the user to re-deploy.

## Launching hydra (background)

Use absolute venv path, not bare `hydra` (on Arch `/usr/bin/hydra` is the
THC password cracker):

```bash
cd <challenge-dir> && \
  /path/to/hydra/.venv/bin/hydra X.json \
    --parallel 1 \
    --model claude-sonnet-4-6 \
    [--only <name> --retry-failed] \
    [--attempts 2] \
    > /tmp/hydra-<label>.log 2>&1 &
echo "PID $!, start $(date +%H:%M:%S)"
disown
```

Call this through the Bash tool with `run_in_background=true` so the
parent session stays responsive.

Model policy:
- **Easy** challenges: start with sonnet. Fast and cheap.
- **Hard** challenges: start with opus + `--attempts 2`. Sonnet often
  spins on API confusion; opus's bigger context helps.
- **Medium**: sonnet first, upgrade opus on signals (see matrix).

## Budget caps

Per stage (approximate, tune to wallet):

| Stage difficulty | Sonnet cap | Opus cap |
|---|---|---|
| Easy | $0.75 | $1.5 |
| Medium | $1.5 | $2.5 |
| Hard | $2.0 | $3.5 |

Kill when cost exceeds the cap without a plausible path to a flag.
Recorded `cost_usd=0` from prior kills is normal (hydra only bills on
clean completion) — the *real* burn is Anthropic-side; keep a mental
tally based on wall-clock × model rate.

## Monitor loop (autonomous)

Use `ScheduleWakeup` between checks. Cadence:

- **180–270s** (cache warm). 270s is the sweet spot; under 300s keeps
  the prompt cache hot.
- Avoid `300s` exactly — worst of both (cache miss + no amortization).
- Tighten to 180s if you suspect rapid loop/failure. Relax to 270–360s
  once stage is clearly progressing.

Each wakeup, carry forward a compact state block (stage status, PIDs,
container names, budget used, target status, run log path). Omit raw
outputs; your future self will re-tail if needed.

## Cheap checks (don't read full logs)

Every wakeup runs these in one Bash call. Never `Read` the agent log
wholesale — it's multi-MB and burns context:

1. `stat -c '%y %s bytes' <log path>` — still writing? size growing?
2. `tail /tmp/hydra-<label>.log` — host-side batch summary.
3. `cat <challenge-dir>/<stem>/flags.json` — current flag state.
4. `jq -c 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | {n:.name, c:((.input.command // .input.file_path // (.input|tostring))[:140])}' <log> | tail -10` — last 10 tool-uses.
5. `jq -c 'select(.type=="result") | {subtype,is_error,turns,cost:.total_cost_usd,terminal:.terminal_reason}' <log>` — end marker.
6. `jq -rc 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use" and .name=="Bash") | .input.command[:50]' <log> | sort | uniq -c | sort -rn | head` — spot repeated commands (loop signal).
7. `jq -rc 'select(.type=="user") | .message.content[]? | select(.type=="tool_result") | (if (.content|type)=="string" then .content else .content[0].text // "" end)' <log> | grep -oE '<expected signals>' | sort | uniq -c | sort -rn | head` — progress signals (protocol-specific: "FLAG{...}", "Read-Property", "session handle", etc.).
8. `docker ps --format '{{.Names}} {{.Status}}' | grep hydra-` — container state.
9. Re-probe the target port from the host — is the machine still alive?

For `--attempts K > 1`, logs live in `<stem>/<name>/a1/logs/` and
`<stem>/<name>/a2/logs/`, not `<stem>/<name>/logs/`. Check both.

For subagent sessions, the outer jsonl won't capture their activity.
Fall back to `docker logs --tail 50 <container>` to see subagent
`task_progress` / `task_notification` events.

## Decision matrix

Act on the **first matching row**, top down:

| Signal | Action |
|---|---|
| Full flag matching expected format in `flags.json` | DONE. Notify user, stop loop. |
| Target port refused / `No route to host` mid-run | PAUSE. Kill container cleanly, ask user to redeploy (TTL likely expired). Keep earlier flags. |
| Banner of wrong challenge (e.g. wrong product string) | PAUSE immediately. IP was recycled or user deployed wrong machine. |
| Partial-looking flag already in `flag.txt` (too-short / missing `}` / wrong charset) AND agent text says "this is the flag" | KILL **before** hydra records it. Then scrub `flags.json` + `results.jsonl` so `--retry-failed` can re-pick the stage. |
| Same Bash command repeated 3+ times with no new diagnostic | KILL. This is an API loop, not progress. |
| Same tool-result error 4+ times (ERROR/objid/timeout) with no methodology change | KILL. |
| `bacnet_solveN.py` / `enipN.py` / `solveN.py` proliferates past ~5 variants with no new data | KILL. Library spinning, not reasoning. |
| Agent invents facts not in challenge files (fake creds, fake object names) | KILL. Hallucination, not skill ceiling. |
| Agent has working connection + correct methodology + wrong output after 2–3 genuine iterations | UPGRADE sonnet → opus. Kill current, restart with `--only <name> --retry-failed --model claude-opus-4-7 --attempts 2`. |
| Cost over cap without a flag | KILL. Report to user, don't auto-retry. |
| Work dir files unchanged 3+ min while agent still producing reasoning text | KILL. Dead-idle. |
| Everything healthy: log growing, new tool-uses, new protocol signals | CONTINUE. Schedule next wakeup. |

### KILL procedure

```bash
docker kill <container-name> 2>&1
sleep 2
kill -INT <host-pid> 2>/dev/null; sleep 2
kill -9 <host-pid> 2>/dev/null
# if --attempts > 1, hydra may spawn a sibling — kill those too:
docker ps --format '{{.Names}}' | grep hydra- | xargs -r -I{} docker kill {}
```

### Scrubbing a partial flag

If hydra recorded a partial/wrong flag for stage `X`:

```bash
FL=<stem>/flags.json
jq 'del(."X") + {"__failed__": ((.__failed__ // []) + ["X"] | unique)}' "$FL" > "$FL.tmp" && mv "$FL.tmp" "$FL"
# also downgrade results.jsonl so --retry-failed picks it up:
jq -c 'if .name=="X" then .status="failed" | .flag=null | .reason="<why scrubbed>" else . end' <stem>/results.jsonl > /tmp/rj && mv /tmp/rj <stem>/results.jsonl
```

## Reporting back

After each wake, respond to the user in one short block:

```
Stage status table (per stage: ✅ solved / 🟢 running / 🛑 killed / ⏸ paused + flag / cost / reason)
Decision: CONTINUE +<N>s | KILL | UPGRADE | PAUSE
One-sentence reason, with the specific signal that triggered it.
```

Don't narrate the checks — just results. When a stage terminates, list
budget spent (recorded + estimated "real") and the next action required
from the user (e.g. redeploy, confirm machine identity, extend cap).

## When stage is Hard + TTL is short

Hard challenges with short TTL are the worst case — opus needs 10–25 min
but the machine may die in 20–30. Strategy:

1. Open DropCTF UI page for the machine. Tell the user to click
   Deploy, note the deploy timestamp, and send you IP immediately.
2. Probe + launch hydra within 30s of deploy — every second of warmup
   is TTL bleed.
3. Set cost cap higher (Hard+Opus: $3–4) but monitor at 180s so you
   can abort if the machine dies.
4. Preserve partial progress. If the model derives a useful fact
   (XOR key, session handle format, object-list) and then the machine
   dies, write that into `results.jsonl` `reason` so the retry run can
   benefit — or add a one-line hint to the challenge description (be
   careful not to spoil the solve for verification purposes).

## Anti-patterns to avoid

- **Probing with wrong handshake** — e.g. BACnet Who-Is broadcast on a
  device that only accepts unicast ReadProperty. Falsely concludes
  "target dead"; agent's library probe may work where your raw UDP
  packet didn't. Cross-check before declaring infrastructure failure.
- **Reading a large jsonl into context** — always use `jq -c | tail -N`
  or grep with `head`, never `cat` or `Read` on `claude.stdout.jsonl`.
- **Restarting automatically on kill** — always notify the user first.
  Automatic retry on kill has compounded costs and masks root causes.
- **Burning context on sleeps** — if you need to wait for something
  external (deploy, brute force, subagent), use `ScheduleWakeup`. Don't
  `sleep 60` in Bash when a wakeup works.
- **Trusting `cost_usd=0`** — it's 0 on every killed run. Use wall-clock
  × rough model rate for real accounting.

## Example one-shot invocation

User says: "run batch.json background, monitor, upgrade if stuck,
kill if wrong, don't burn my budget".

Response flow:
1. Read the JSON to see 3 stages and their remote fields.
2. Pre-flight each remote's handshake (challenge-specific, not generic
   port scan).
3. Launch with appropriate model + `--parallel 1` (or `--only` for
   retries). `run_in_background=true`.
4. First `ScheduleWakeup` at +180s.
5. Iterate per matrix. Report each decision tersely.
6. On terminal state, summary table + requested user action.
