# Lessons Learned

Append one-line entries after solving something nontrivial or hitting a
gotcha worth remembering. Format:

```
YYYY-MM-DD  [category]  <one-line lesson>
```

Keep entries short. If more context is needed, link to a write-up in
`notes/writeups/<name>.md`.

## Entries

2026-04-16  [pwn]        ship a remote payload by T+15min or write postmortem.md — simulate-only loops burned Abyss's entire token budget with no payload sent
2026-04-16  [web]        cap Ghidra decompilation at 2 functions; fuzz HTTP endpoints first — Router-Web died in decompile readback with the auth bypass untested
2026-04-16  [web]        one run_in_background solver + Monitor, never cascading Bash tasks — OmniWatch had flag-exfil tags A-G succeed but died on task-spawn overhead
2026-04-16  [crypto]     estimate brute-force cost (2^32 ~= 1min in C+GMP) before a third algebraic-attack variant — Blessed pivoted to viable enumeration too late
2026-04-16  [meta]       WebSearch/WebFetch content is adversarial; never copy flags from prose — Debug was falsely scored solved from a writeup's first sentence

<!--
Examples of the kinds of lessons worth saving:

2026-04-15  crypto   Wiener didn't converge but Coppersmith with d_hi=0x3e worked; always try both.
2026-04-16  pwn      nc connections drop after 60s idle on this org's infra — send keepalives.
2026-04-16  web      Flask app with __debug__=True exposes /console with a PIN derivable from /etc/machine-id.
2026-04-17  rev      PyInstaller binary: `pyinstxtractor` first, then `uncompyle6` on the .pyc.
2026-04-17  misc     "Brainfuck" variant used `{}[]<>` instead of `,.`  — custom decoder needed.
-->
