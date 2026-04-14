# Handoff Protocol — typed cross-specialist escalation

When a specialist concludes it can't solve the challenge, or discovers the
challenge was misclassified, it can hand off to the triage agent via a
structured sidecar file. The triage agent reads the file and re-dispatches
to a different specialist — with context intact.

Adapted from CAI's typed `handoff()` with `EscalationData(reason: str)`
(arxiv 2504.06017). The Pydantic model there is just a contract; in Hydra
we use a JSON sidecar for the same purpose.

## When to hand off

Write a handoff file when any of these are true after you've spent your
budget:

- **Misclassification detected.** You were dispatched as `rev-specialist`
  but the binary is a thin wrapper whose real work is crypto — hand to
  `crypto-specialist`.
- **Out of category.** You're `web-specialist` but the flag requires
  reverse-engineering a binary referenced in the web app — hand to
  `rev-specialist`.
- **Need complementary analysis.** You're `forensics-specialist`, extracted
  a custom-protocol binary from a pcap, and need someone to reverse it —
  hand to `rev-specialist`.
- **Totally stuck.** You've made no progress, you can see the category is
  right, but you need a fresh perspective — hand back to the same
  specialist with an explicit hint.

Do **not** hand off as an excuse to give up after one pass. The triage
agent has a limit of two re-dispatches total per challenge, so each one
must be principled.

## Handoff file format

Write to `./work/handoff.json` atomically (write to `.tmp`, rename):

```json
{
  "from": "rev-specialist",
  "to": "crypto-specialist",
  "reason": "binary is a 200-byte ELF that calls mbedtls AES-128-CBC with a hardcoded key and reads ciphertext from argv[1]. Flag is the plaintext. This is crypto in a rev wrapper.",
  "evidence": [
    "./work/ltrace.log",
    "./work/ghidra-decompile-main.c",
    "./work/extracted-key.hex"
  ],
  "hint": "key is in ./work/extracted-key.hex, ciphertext is ./challenge/ct.bin, IV is first 16 bytes of ct.bin",
  "already_tried": [
    "angr explore to win address — state explosion",
    "r2 patching jne — still needs valid decryption to print flag"
  ]
}
```

Required fields:
- **`from`**: your specialist name
- **`to`**: target specialist (`pwn-specialist`, `crypto-specialist`, etc.)
- **`reason`**: one sentence, why the other specialist is better placed
- **`hint`**: the specific thing the target should try first (not "try
  harder" — a concrete entrypoint)

Optional but highly useful:
- **`evidence`**: paths under `./work/` the target should read. Do not
  re-explain what's in those files; point to them.
- **`already_tried`**: things you tried that didn't work. Prevents the
  target from repeating them.

## Triage behavior on handoff

The triage agent, after waiting for a specialist:
1. If `./flag.txt` is present and passes verification → done.
2. Else, if `./work/handoff.json` exists:
   - Parse it.
   - Dispatch `to` specialist with the original challenge context **plus**
     the `reason`, `hint`, `evidence` paths, and `already_tried` list in
     the dispatch prompt.
   - Decrement the re-dispatch budget.
3. Else, apply the normal re-dispatch rules.

## What NOT to put in a handoff file

- Do not paste full tool outputs into `reason` or `hint`. Point at files
  under `./work/` instead. The target will read what it needs.
- Do not put the flag in a handoff file. If you had the flag, you'd have
  written it to `./flag.txt`.
- Do not hand off without writing the evidence files first. An empty
  `./work/` with a handoff asking the next specialist to "try crypto" is
  useless.

## Self-hand-off (same specialist, new hint)

Perfectly valid:

```json
{
  "from": "pwn-specialist",
  "to": "pwn-specialist",
  "reason": "stack layout confirmed; need to build a ROP chain targeting a different gadget set than I first tried",
  "hint": "the challenge ignores %p input but accepts %s — format string leak is the right primitive, not BOF",
  "evidence": ["./work/binary-info.md", "./work/leak-attempt.py"],
  "already_tried": ["plain BOF — canary caught it", "libc ret2one-gadget — none had the right constraints"]
}
```

The triage agent treats this as "re-dispatch same specialist with hint",
which is weaker than a category pivot but still costs one budget slot.

## Reference

- **CAI** (arxiv 2504.06017): typed handoff with `EscalationData`. Source:
  `src/cai/agents/patterns/bb_triage.py`,
  `examples/handoffs/message_filter.py`.
- **CAI docs**: `docs/handoffs.md`.
- **Cybench** (arxiv 2408.08926): evidence that explicit task decomposition
  helps on hard challenges — handoff is decomposition-at-dispatch-time.
