# CTF → challenges.json ingest

Convert messy, copy-pasted CTF challenge text into a valid hydra
`challenges.json` file. **Read this file once, parse the raw text the
user pasted, write the JSON — done.** Do not ask clarifying questions
unless the text is genuinely ambiguous.

## Invocation

The user pastes raw CTF text above/below an instruction like:

```
<raw challenge text, any format>

read prompts/ctf-ingest.md and save as <filename>.json
```

Your job:
1. Parse the raw text into one or more challenge objects.
2. Write a JSON array to the filename the user gave (default: `challenges.json`).
3. Print a ~3-line summary (count, names, category breakdown).

## Target schema

Top-level: JSON array. Each entry is a dict. Hydra accepts several
aliases per field — **always emit the canonical key**:

| Field       | Canonical key | Aliases hydra accepts             | Type         | Required             |
|-------------|---------------|-----------------------------------|--------------|----------------------|
| Name        | `name`        | `title`, `id`                     | string       | no (auto-hashed)     |
| Description | `description` | `prompt`, `task`, `challenge`     | string       | yes, or `files`      |
| Files       | `files`       | `attachments`, `paths`            | list[string] | yes, or `description`|
| Remote      | `remote`      | `host`, `url`, `service`          | string       | optional             |
| Hints       | `hints`       | `hint`                            | list[string] | optional             |
| Category    | `category`    | `tag`                             | string       | optional             |
| Points      | `points`      | `score`, `value`                  | integer      | optional             |

Each entry must have **at least one of `description` or `files`**.
Omit optional fields that aren't in the text — don't emit `null` or `""`.

## Parsing heuristics

### Name
- A heading (`# Title`, `## Title`), bold first line, or first line
  before the description is the name.
- Numbered/prefixed ("1. Chal — ...", "Q1: ...", "[pwn] babyrop"):
  strip the prefix, keep the title.
- No obvious title → slug from first 3–5 content words, skipping
  banner nouns like "CTF", "Challenge", "Task", "Problem".
- Filesystem-safe only: lowercase, `[a-z0-9-]`, use `-` between words.
  No slashes, spaces, colons, quotes, dots.

### Category (infer from keywords, case-insensitive)
- `rsa|aes|ecc|hash|prng|cipher|encrypt|decrypt|signature|lattice` → `crypto`
- `http|url|cookie|SQL|JWT|SSTI|SSRF|XSS|CMS|login|upload|flask|django|php` → `web`
- `ELF|pwntools|libc|stack|heap|ROP|canary|shellcode|buffer overflow|\bnc \w` → `pwn`
- `binary|reverse|ghidra|IDA|decompile|angr|disassemble|strings` → `rev`
- `pcap|memory dump|stego|\.png|\.wav|\.jpg|\.jpeg|volatility|wireshark|tshark|disk image` → `forensics`
- `OSINT|Google|Wayback|esoteric|rot13|base64|brainfuck|morse` → `misc`
- Multiple categories match → pick the strongest; if truly ambiguous,
  omit — hydra's triage agent classifies at runtime.

### Description
- Everything between the title and the next structural marker
  (`Hints:`, `Attachments:`, `Connect:`, next challenge heading, `---`).
- **Preserve verbatim**: commands, URLs, `nc host port`, filenames,
  asterisk-count markers (`***` = 3-char answer), code fences, ASCII art.
- Strip surrounding whitespace and any wrapping markdown code fences
  *that wrap the whole description*; keep code fences *inside* it.
- Preserve the original language (Thai, English, Japanese…) —
  never translate, summarize, or paraphrase.

### Hints
- Lines starting with `Hint:`, `Hint 1:`, `Hints:`, `💡`, `ℹ️`.
- Blocks titled `Hints`, `Hints:`, or between `<details>` tags labeled hint.
- Each hint is a separate string in the `hints` list.
- Do NOT invent hints. If the text has none, omit the field.

### Remote
Match patterns in priority order, first hit wins:
- `nc <host> <port>` → `"nc host port"` (keep as-is, hydra reads literals)
- `ssh <user>@<host>[:port]` → as-is
- `https?://...` → as-is
- `host.tld:port` (bare socket) → as-is
- "Target IP: 10.x.x.x" / "target: 10.x.x.x" → `"10.x.x.x"`
- Ignore unrelated URLs (GitHub repos, writeups, image hosts).

### Files
- `Attachment: chal.zip`, `Files: a.py, b.txt`, inline filenames
  clearly given as the challenge binary (`./vuln`, `chal.py`,
  `server.tar.gz`).
- Include only filenames *the user will have locally*. A "download
  from <url>" link goes in `remote` instead; do not fabricate paths.
- If the text gives a full path like `/tmp/pwn1` use it verbatim.

### Points
- First integer before `pt`, `pts`, `points`, `Difficulty:`, `score:`.
- Leave off if absent. Do not guess from labels like "easy / medium / hard".

## Multiple challenges in one blob

Emit one array entry per challenge when you see any of:
- Repeated `##`/`###` headings at the same level
- Numbered list with distinct challenges (`1.`, `2.`, …) each with their own prompt
- `---` / `===` separators between blocks
- Multiple `Target:` / `Connect:` values in one text

Emit one entry when:
- Single coherent task even if multi-paragraph
- Numbered list is *questions about one challenge* (like TryHackMe rooms)
- Hints reference "this challenge" (singular)

When unsure, prefer **one entry** — easier to split later than to merge.

## Non-negotiables

- **Don't fabricate.** If a field isn't in the text, omit it. Never
  guess creds, URLs, flag formats, or files.
- **Don't translate or rewrite** the description.
- **Don't normalize prose** — preserve typos, weird spacing inside code,
  non-ASCII characters.
- **Don't submit a flag.** This prompt ingests *challenges*, not flags.
  If the text includes a flag value, omit it entirely — it's either an
  example or a decoy.

## Write + verify

1. Build the array in memory.
2. Mentally `json.loads` it — parse cleanly? All strings escaped?
3. Unique names? If collision, suffix `-2`, `-3`, …
4. Each entry has `description` OR `files`?
5. Use the **Write** tool (not `Bash echo` — heredocs corrupt on
   special chars, smart quotes, or embedded backticks).
6. Print a summary — one line like:
   ```
   wrote simple-ctf.json (1 challenge: simple-ctf [misc])
   ```
   or for multi:
   ```
   wrote picoctf-crypto.json (7 challenges: 4 crypto, 2 misc, 1 unknown)
   ```

## Examples

### 1. Single THM-style room

**Input (pasted):**
```
# Simple CTF

TryHackMe room. Target: 10.10.10.10 (machine deployed, be quick).

Questions:
1. Services under port 1000? (*)
2. What CVE? (*************)
...
Hint: nmap -sV first; check the CMS version.
```

**Output (`simple-ctf.json`):**
```json
[
  {
    "name": "simple-ctf",
    "category": "misc",
    "description": "TryHackMe room. Target: 10.10.10.10 (machine deployed, be quick).\n\nQuestions:\n1. Services under port 1000? (*)\n2. What CVE? (*************)\n...",
    "hints": ["nmap -sV first; check the CMS version."],
    "remote": "10.10.10.10"
  }
]
```

### 2. picoCTF-style multi-challenge export

**Input:**
```
## Mod 26 (100 pts)
Category: Cryptography
Decrypt this: vszzc rcfzr
flag format: picoCTF{...}

## RSA Weak Modulus (300 pts)
Category: Cryptography
Given n=... and c=... Factor n.
Files: chal.py, pubkey.txt
Hint: n is suspiciously small.
```

**Output (`picoctf.json`):**
```json
[
  {
    "name": "mod-26",
    "category": "crypto",
    "points": 100,
    "description": "Decrypt this: vszzc rcfzr\nflag format: picoCTF{...}"
  },
  {
    "name": "rsa-weak-modulus",
    "category": "crypto",
    "points": 300,
    "description": "Given n=... and c=... Factor n.",
    "files": ["chal.py", "pubkey.txt"],
    "hints": ["n is suspiciously small."]
  }
]
```

### 3. pwn with remote + file

**Input:**
```
babyrop — 400 pts [pwn]

Classic ret2libc. Binary attached (babyrop ELF 64-bit).
Connect: nc pwn.ctf.example.com 31337
No PIE, no canary, partial RELRO.
```

**Output (`babyrop.json`):**
```json
[
  {
    "name": "babyrop",
    "category": "pwn",
    "points": 400,
    "description": "Classic ret2libc. Binary attached (babyrop ELF 64-bit).\nNo PIE, no canary, partial RELRO.",
    "files": ["babyrop"],
    "remote": "nc pwn.ctf.example.com 31337"
  }
]
```

### 4. Thai-language misc challenge (preserve language)

**Input:**
```
ชาเลนจ์: รหัสแปลก ๆ
ถอดรหัสข้อความนี้: 01010000 01000011
คำใบ้: binary to ASCII
```

**Output (`thai-cipher.json`):**
```json
[
  {
    "name": "รหัสแปลก",
    "category": "misc",
    "description": "ถอดรหัสข้อความนี้: 01010000 01000011",
    "hints": ["binary to ASCII"]
  }
]
```

(Note: if the Thai name causes filesystem issues later, hydra will
pass it through `safe_name()` — it handles Unicode letters fine.)

---

Now parse the raw text the user pasted and write the JSON. Don't echo
the JSON to stdout — use the Write tool and save the summary message
for the user.
