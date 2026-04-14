# Interactive Agent Tools (IAT) Pattern

EnIGMA (2409.16165) observed that wrapping *interactive* CLIs (gdb, r2,
server nc connections) in a persistent, addressable session boosts agent
solve rates significantly. The key insight: raw shell calls are
stateless; many CTF workflows are fundamentally stateful.

See `.claude/skills/pwn/tmux-session.md` for the concrete tmux recipe.
This file documents the general pattern and when to apply it.

## The pattern

```
┌────────────────┐                ┌────────────────┐
│ Your Bash call │  send-keys →   │ tmux session   │  (persistent)
│ (stateless)    │  ← capture-pane│ hosting <tool> │
└────────────────┘                └────────────────┘
```

- Start: `tmux new-session -d -s <name> "<command>"`
- Send: `tmux send-keys -t <name> 'text' Enter`
- Read: `tmux capture-pane -t <name> -p -S -500`
- Stop: `tmux kill-session -t <name>`

The tool inside the session doesn't need to know about tmux. From its
perspective, someone's typing at a real terminal.

## Target tools that benefit most

| Tool | Why it benefits | Session name convention |
|------|-----------------|-------------------------|
| `nc host port` | Multi-turn protocol, connection state | `pwn` |
| `gdb` / `pwndbg` | Breakpoints, watchpoints, register inspection across calls | `gdb` |
| `r2` (interactive) | Symbol table + cursor position | `r2` |
| `sqlmap --os-shell` | Interactive DB/OS shell | `sql` |
| `msfconsole` / `msf6` | Module state, session handles | `msf` |
| `python3 -i` | REPL state (variables, imports) | `py` |
| `pari-gp` (`gp`) | Number-theory CLI state, fast factoring | `gp` |
| `ssh host` | Shell history, env state | `ssh` |

## Naming & isolation

Use one session per tool/target, named after the tool. If you run two
instances (e.g., two nc connections), suffix: `pwn-1`, `pwn-2`.

Kill sessions when you're done to free resources and avoid stale state
leaking into the next solve.

## Scripting inside the session

Inside the tmux session, the tool's stdin is being sent text byte by
byte. If you need to send arbitrary bytes (not just ASCII), use the
tool's own input capability:
- gdb: `x/s`, `set *(char*)0xaddr = 0x41`
- python3 -i: type `import runpy; runpy.run_path("payload.py")`
- nc in pipe mode: restart the session as `nc host 1337 < payload.bin`

For raw-binary pwn payloads, pwntools' `remote()` is still easier. Use
tmux for tools that have their own interactive command language.

## Gotchas

- **Capture lag.** After `send-keys`, wait 100-300ms before
  `capture-pane` — the server needs time to respond.
- **Scroll truncation.** `capture-pane` without `-S -N` shows only
  visible pane. Use `-S -500` (last 500 lines) or `-S -` (all scrollback).
- **ANSI colors and TUIs.** Programs that draw TUIs (htop, ncurses-based
  tools) produce capture-pane output that's hard to parse. Prefer
  non-TUI mode flags (`--no-color`, `--no-tui`, `--batch`).
- **Process death.** If the tool inside the session dies (remote hangs
  up, gdb crashes), the session becomes a dead shell. Always check
  `tmux has-session -t <name>` before sending.

## Reference

- **EnIGMA** (arxiv 2409.16165) — "Interactive Agent Tools" design, solve
  rate improvements on pwn/rev categories.
- **NYU CTF Bench** (arxiv 2406.05590) — similar tmux-based pattern in
  their agent.
