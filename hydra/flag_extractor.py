import re
from pathlib import Path

_SPECIFIC = [
    re.compile(r"(?<![A-Za-z0-9_])flag\{[^}]+\}"),
    re.compile(r"(?<![A-Za-z0-9_])FLAG\{[^}]+\}"),
    re.compile(r"(?<![A-Za-z0-9_])CTF\{[^}]+\}"),
]
_GENERIC = re.compile(r"[A-Za-z0-9_]+\{[^}]+\}")
_FLAG_LINE = re.compile(r"FLAG:\s*(\S+)")

# Hard cap on the body inside `{...}`. Longest real HTB flag seen so far
# is ~95 chars; 128 is comfortable. Anything longer is almost always a
# writeup excerpt or a prompt-injection payload.
_MAX_BODY_LEN = 128

# If a flag body contains any of these substrings, it's junk from a
# WebSearch result / writeup, not a real flag.
_BANNED_BODY_SUBSTRINGS = (
    "REMINDER",
    "http://",
    "https://",
    "```",
    "<|",
    "IGNORE PREVIOUS",
    "ignore previous",
)


def extract_flag(*, flag_file: Path, stdout: str) -> str | None:
    # Priority 1: flag.txt
    if flag_file.exists():
        content = flag_file.read_text().strip()
        if content and _looks_like_flag(content):
            return content

    # Priority 2: last "FLAG: <value>" line
    line_matches = _FLAG_LINE.findall(stdout)
    if line_matches:
        candidate = line_matches[-1]
        if _looks_like_flag(candidate):
            return candidate

    # Priority 3: regex sweep — specific first, then generic, last *valid* match wins
    for pat in _SPECIFIC:
        hits = [h for h in pat.findall(stdout) if _looks_like_flag(h)]
        if hits:
            return hits[-1]
    hits = [h for h in _GENERIC.findall(stdout) if _looks_like_flag(h)]
    if hits:
        return hits[-1]
    return None


def _looks_like_flag(s: str) -> bool:
    m = _GENERIC.fullmatch(s)
    if not m:
        return False
    # Extract body between first `{` and last `}` of the fullmatch.
    open_idx = s.index("{")
    body = s[open_idx + 1 : -1]
    if not body:
        return False
    if len(body) > _MAX_BODY_LEN:
        return False
    # A real flag body has no whitespace (space, tab, CR, LF).
    if any(ch.isspace() for ch in body):
        return False
    # Control / non-printable rejects obfuscated / binary payloads.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in body):
        return False
    for needle in _BANNED_BODY_SUBSTRINGS:
        if needle in body:
            return False
    return True
