# Output Summarization

Before feeding a large, noisy tool output (nmap scan, `binwalk -e` listing,
`strings` dump, volatility plugin output, pcap dissection) back into your
reasoning, **summarize it first**. This keeps the next reasoning turn focused
on what matters and avoids drowning the context in TTY spam.

## When to summarize

Summarize any tool output larger than ~50 lines, or any output with a high
ratio of formatting/banners to actual findings. Common triggers:

- `nmap` full TCP scan
- `gobuster` or `ffuf` after a dictionary run
- `binwalk -e <file>` extraction listing
- `strings <binary> | head -500`
- `volatility pslist/psscan/pstree` full dump
- `tshark -r pcap -V` verbose dissection
- Ghidra headless script output
- `angr` explore logs

## How to summarize

Write a compact summary to `./work/<tool>-summary.md` (or append to an existing
file for the same artifact). Structure:

```markdown
# <tool> — <artifact>

Ran: <exact command>

## Findings (one line each, most useful first)
- <finding>: <field>=<value>
- <finding>: <field>=<value>

## Notes
- <anything that might matter later but isn't an actionable finding>
```

## The one rule: summarize only, do not conclude

You are not deciding the next step here. You are distilling facts.

**Good:**
- `port 80 open, nginx 1.24.0`
- `binwalk found: Squashfs filesystem at 0x200000`
- `volatility pslist: 3 processes named "notepad.exe", one PID=4420 with unusual parent`

**Bad (these belong in the next reasoning turn, not here):**
- "port 80 is open so we should run gobuster next"
- "this process is probably malicious"
- "the Squashfs is where the flag probably is"

Keeping summarization free of conclusions is important because the summary
might get re-read days later when the context is different, or handed to a
different specialist. Conclusions rot; facts keep.

## Field-name-plus-value discipline

Always include both the field name and the value. `open ports: 22, 80` is
useless three minutes later. `22/tcp open ssh OpenSSH 9.6`, `80/tcp open
http nginx 1.24.0` is what you'll actually need when you pivot.

## When not to summarize

- Output is already ≤10 lines and mostly findings (e.g., `file ./bin`).
- Output is a single value you need verbatim (a hash, a flag candidate, a
  base64 blob for another tool).
- You're in a tight pivot loop and summarization would slow you down —
  just keep the raw output in the reasoning context for one more turn.

## Reference

- **PentestGPT** (arxiv 2308.06782): explicit reasoning/generation/parsing
  module split. The parsing module has exactly one directive — *"summarize,
  do not conclude"* — and the paper attributes a chunk of the 228.6%
  task-completion improvement to keeping conclusions out of the parsing
  step. Source: `legacy/pentestgpt/prompts/prompt_class_v2.py`
  `input_parsing_init`.
- **Cybench** (arxiv 2408.08926): context management matters more as
  sessions grow; summarized outputs keep later turns sharp.
