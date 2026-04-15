import hashlib
import re
from pathlib import Path
from typing import Any
from hydra.models import Challenge

class NormalizationError(Exception):
    pass

_NAME_KEYS = ("name", "title", "id")
_DESC_KEYS = ("description", "prompt", "task", "challenge")
_FILES_KEYS = ("files", "attachments", "paths")
_REMOTE_KEYS = ("remote", "host", "url", "service")
_HINTS_KEYS = ("hints", "hint")
_CAT_KEYS = ("category", "tag")
_POINTS_KEYS = ("points", "score", "value")

def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]

def safe_name(s: str) -> str:
    # Replace filesystem-hostile chars; keep unicode letters.
    out = re.sub(r"[\s/\\:]+", "-", s)
    out = re.sub(r"\.+", "", out)
    return out or "unnamed"

def _normalize_one(raw: dict[str, Any], idx: int) -> Challenge:
    name = _first(raw, _NAME_KEYS)
    desc = _first(raw, _DESC_KEYS) or ""
    files_raw = _as_list(_first(raw, _FILES_KEYS))
    files = [Path(p) for p in files_raw]

    if not name:
        seed = (desc + str(files)).encode()
        name = "chal-" + hashlib.sha1(seed).hexdigest()[:8]

    if not desc and not files:
        raise NormalizationError(
            f"entry #{idx} ({name!r}) has no description and no files"
        )

    hints = _as_list(_first(raw, _HINTS_KEYS))
    points = _first(raw, _POINTS_KEYS)

    return Challenge(
        # safe_name strips filesystem-hostile chars so the challenge name
        # can be used as a directory (runs/<name>/, failures/<name>.md)
        # without risking path traversal from untrusted input.
        name=safe_name(str(name)),
        description=str(desc),
        files=files,
        remote=_first(raw, _REMOTE_KEYS),
        hints=[str(h) for h in hints],
        category=_first(raw, _CAT_KEYS),
        points=int(points) if points is not None else None,
    )

def normalize_challenges(raw: Any) -> list[Challenge]:
    if not isinstance(raw, list):
        raise NormalizationError("top-level JSON must be a list")

    out: list[Challenge] = []
    seen: dict[str, int] = {}
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise NormalizationError(f"entry #{idx} is not an object")
        c = _normalize_one(entry, idx)
        # De-duplicate names by appending -2, -3, ...
        base = c.name
        count = seen.get(base, 0)
        if count > 0:
            c = Challenge(**{**c.__dict__, "name": f"{base}-{count+1}"})
        seen[base] = count + 1
        out.append(c)
    return out
