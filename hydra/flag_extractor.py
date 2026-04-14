import re
from pathlib import Path

_SPECIFIC = [
    re.compile(r"(?<![A-Za-z0-9_])flag\{[^}]+\}"),
    re.compile(r"(?<![A-Za-z0-9_])FLAG\{[^}]+\}"),
    re.compile(r"(?<![A-Za-z0-9_])CTF\{[^}]+\}"),
]
_GENERIC = re.compile(r"[A-Za-z0-9_]+\{[^}]+\}")
_FLAG_LINE = re.compile(r"FLAG:\s*(\S+)")

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

    # Priority 3: regex sweep — specific first, then generic, last match wins
    for pat in _SPECIFIC:
        hits = pat.findall(stdout)
        if hits:
            return hits[-1]
    hits = _GENERIC.findall(stdout)
    if hits:
        return hits[-1]
    return None

def _looks_like_flag(s: str) -> bool:
    return bool(_GENERIC.fullmatch(s))
