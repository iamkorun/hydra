# Tmux Persistent Sessions for Pwn

Many pwn challenges require a long-lived interactive session: connect once
with `nc host port`, exchange dozens of messages across the same
connection, keep state across shell calls. A fresh `nc` per Bash call
drops the connection and loses state. Tmux solves this.

**When to use:** any remote pwn service that expects a multi-turn exchange
over one TCP connection. Also useful for `gdb` interactive debugging where
you want breakpoints to persist across your tool calls.

## Pattern

### 1. Start a detached session with the connection

```bash
tmux new-session -d -s pwn "nc host 1337"
# or, with gdb attached to a local binary:
tmux new-session -d -s pwn "gdb ./challenge/bin"
```

The `-d` keeps it detached — your shell returns immediately while the
connection stays alive.

### 2. Send keystrokes to it

```bash
# Literal text + Enter
tmux send-keys -t pwn 'hello' Enter

# Multiple lines, useful for scripted exploits
tmux send-keys -t pwn 'AAAA' Enter 'cat flag' Enter
```

### 3. Read what's on screen

```bash
# Dump the current visible pane to stdout
tmux capture-pane -t pwn -p

# Full scrollback (last N lines)
tmux capture-pane -t pwn -p -S -1000
```

### 4. Clean up when done

```bash
tmux kill-session -t pwn
```

## Complete minimal workflow in a solve.py

```python
import subprocess, time

def send(keys):
    subprocess.run(["tmux", "send-keys", "-t", "pwn"] + keys)

def read():
    return subprocess.check_output(
        ["tmux", "capture-pane", "-t", "pwn", "-p", "-S", "-200"]
    ).decode()

# Start
subprocess.run(["tmux", "new-session", "-d", "-s", "pwn", "nc", "host", "1337"])
time.sleep(0.3)
print(read())

send(["overflow_payload", "Enter"])
time.sleep(0.5)
print(read())

# After you've got the flag or shell
subprocess.run(["tmux", "kill-session", "-t", "pwn"])
```

## Gotchas

- `send-keys` is literal — shell metacharacters (`$`, quotes) may need `-l` (literal) mode.
- Binary payloads don't survive `send-keys` well. For arbitrary bytes use pwntools' `remote()` or pipe into a here-doc.
- Capture-pane shows visible screen; use `-S -N` to go back N lines into scrollback.
- Default terminal size inside tmux is 80x24. For wide hex dumps, resize: `tmux set -s default-terminal-size 200x50` before `new-session`.

## When NOT to use tmux

- Single round-trip request/response → just `curl` or `nc -q1`.
- Structured bin protocol → pwntools `remote()` / `p.sendline()` are nicer.
- One-shot exploit you only run once → pwntools `process()` in solve.py.

Tmux shines when the agent needs to iterate: send a byte, read the response, adjust, send the next payload — across multiple reasoning turns.
