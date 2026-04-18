"""Pre-commit flag gate: veto partial/malformed/mismatched flags before
they land in flags.json. Pure function — zero tokens, zero network.

Runs between flag_extractor.extract_flag() and ResultsWriter.append(),
so a REJECT keeps `flags.json` clean and `--retry-failed` can re-pick
the challenge. WARN demotes status to the existing `solved_uncertain`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from hydra.models import Challenge

_MAX_BODY_LEN = 128
_MIN_BODY_LEN = 1
_STRUCT_RE = re.compile(r"^([A-Za-z0-9_]+)\{([^}]+)\}$")


class Verdict(str, Enum):
    ACCEPT = "accept"
    WARN = "warn"
    REJECT = "reject"


@dataclass(frozen=True)
class GateVerdict:
    verdict: Verdict
    reason: str | None = None


def check(candidate: str, challenge: Challenge, workdir: Path) -> GateVerdict:
    """Gate a flag candidate. REJECT > WARN > ACCEPT.

    REJECT rules are structural: if any fire, the candidate never
    reaches flags.json. WARN rules flag derivation-evidence problems;
    they demote to solved_uncertain so the human can double-check
    before submitting.
    """
    candidate = candidate.strip()

    # --- REJECT rules (structural / format) ---
    if "{" in candidate and not candidate.rstrip().endswith("}"):
        return GateVerdict(Verdict.REJECT, "unclosed brace in flag")
    m = _STRUCT_RE.fullmatch(candidate)
    if not m:
        return GateVerdict(Verdict.REJECT, "malformed: does not match PREFIX{body}")
    prefix, body = m.group(1), m.group(2)
    if len(body) < _MIN_BODY_LEN or len(body) > _MAX_BODY_LEN:
        return GateVerdict(Verdict.REJECT, f"length {len(body)} out of bounds")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in body):
        return GateVerdict(Verdict.REJECT, "control char in body")
    if any(c.isspace() for c in body):
        return GateVerdict(Verdict.REJECT, "whitespace in body")

    if challenge.expected_format:
        if not re.fullmatch(challenge.expected_format, candidate):
            return GateVerdict(
                Verdict.REJECT,
                f"format mismatch: expected {challenge.expected_format!r}",
            )

    if challenge.flag_prefix and prefix.lower() != challenge.flag_prefix.lower():
        return GateVerdict(
            Verdict.REJECT,
            f"prefix mismatch: got {prefix!r}, expected {challenge.flag_prefix!r}",
        )

    # --- WARN rules (derivation evidence) ---
    prior_log = workdir / "work" / "prior-knowledge.log"
    if prior_log.exists() and prior_log.stat().st_size > 0:
        return GateVerdict(
            Verdict.WARN,
            "prior_knowledge log present — route to verifier-specialist",
        )
    work_dir = workdir / "work"
    if not work_dir.is_dir() or not any(work_dir.iterdir()):
        return GateVerdict(
            Verdict.WARN,
            "no_scratch: agent produced flag without derivation artifacts",
        )

    return GateVerdict(Verdict.ACCEPT)
