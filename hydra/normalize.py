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
_EXPECTED_FORMAT_KEYS = ("expected_format", "flag_format", "format")
_FLAG_PREFIX_KEYS = ("flag_prefix", "prefix")

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
    files: list[Path] = []
    for f in files_raw:
        if not isinstance(f, (str, Path)):
            raise NormalizationError(
                f"entry #{idx} ({name!r}): file path must be a string, "
                f"got {type(f).__name__}: {f!r}"
            )
        files.append(Path(f))

    if not name:
        seed = (desc + str(files)).encode()
        name = "chal-" + hashlib.sha1(seed).hexdigest()[:8]

    if not desc and not files:
        raise NormalizationError(
            f"entry #{idx} ({name!r}) has no description and no files"
        )

    hints = _as_list(_first(raw, _HINTS_KEYS))
    points = _first(raw, _POINTS_KEYS)
    expected_format = _first(raw, _EXPECTED_FORMAT_KEYS)
    flag_prefix = _first(raw, _FLAG_PREFIX_KEYS)
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
        expected_format=str(expected_format) if expected_format is not None else None,
        flag_prefix=str(flag_prefix) if flag_prefix is not None else None,
    )

def normalize_challenges(raw: Any) -> list[Challenge]:
    if not isinstance(raw, list):
        raise NormalizationError("top-level JSON must be a list")

    out: list[Challenge] = []
    taken: set[str] = set()
    base_counts: dict[str, int] = {}
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise NormalizationError(f"entry #{idx} is not an object")
        c = _normalize_one(entry, idx)
        # De-duplicate names by appending -2, -3, ...  Guard against a
        # raw name already matching the suffix we would have generated
        # (e.g. ["foo", "foo", "foo-2"] must not produce two "foo-2"s).
        base = c.name
        if base not in taken:
            taken.add(base)
            base_counts[base] = 1
        else:
            n = base_counts[base] + 1
            candidate = f"{base}-{n}"
            while candidate in taken:
                n += 1
                candidate = f"{base}-{n}"
            base_counts[base] = n
            taken.add(candidate)
            c = Challenge(**{**c.__dict__, "name": candidate})
        out.append(c)
    return out
