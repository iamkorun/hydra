"""Structured flag validation with an accept/warn/reject verdict.

The extractor's fast path (flag_extractor.py) only returns a bool. This
module is what the orchestrator calls when it wants to route candidates
to the verifier-specialist: WARN = send to verifier, REJECT = drop.
"""
from dataclasses import dataclass
from enum import StrEnum
import re

_FLAG_RE = re.compile(r"^([A-Za-z0-9_]+)\{([^}]+)\}$")

_MAX_BODY_LEN = 128

_BANNED_SUBSTRINGS = (
    "REMINDER",
    "http://",
    "https://",
    "```",
    "<|",
    "IGNORE PREVIOUS",
    "ignore previous",
)

_PLACEHOLDER_BODIES = frozenset({
    "test", "example", "fixme", "placeholder", "fake", "redacted",
    "todo", "sample", "your_flag_here", "xxxx",
})


class Verdict(StrEnum):
    ACCEPT = "accept"   # submit as-is
    WARN = "warn"       # route to verifier-specialist; could be a decoy
    REJECT = "reject"   # definitely not a flag, drop


@dataclass(frozen=True)
class Validation:
    verdict: Verdict
    reason: str | None = None


def validate(candidate: str, *, expected_prefix: str | None = None) -> Validation:
    m = _FLAG_RE.fullmatch(candidate)
    if not m:
        return Validation(Verdict.REJECT, "malformed: does not match PREFIX{body}")
    prefix, body = m.group(1), m.group(2)

    # Reject: structurally impossible to be a flag.
    if not body:
        return Validation(Verdict.REJECT, "empty body")
    if len(body) > _MAX_BODY_LEN:
        return Validation(Verdict.REJECT, f"length {len(body)} > {_MAX_BODY_LEN}")
    if any(ch.isspace() for ch in body):
        return Validation(Verdict.REJECT, "whitespace in body")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in body):
        return Validation(Verdict.REJECT, "control char in body")
    for needle in _BANNED_SUBSTRINGS:
        if needle in body:
            return Validation(Verdict.REJECT, f"banned substring: {needle!r}")

    # Warn: looks structurally fine, but could be a decoy.
    if body.lower() in _PLACEHOLDER_BODIES:
        return Validation(Verdict.WARN, f"placeholder body: {body!r}")
    if expected_prefix and prefix.lower() != expected_prefix.lower():
        return Validation(
            Verdict.WARN,
            f"prefix mismatch: got {prefix!r}, expected {expected_prefix!r}",
        )

    return Validation(Verdict.ACCEPT)
