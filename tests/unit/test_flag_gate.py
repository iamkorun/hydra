from pathlib import Path

import pytest

from hydra.flag_gate import Verdict, check
from hydra.models import Challenge


def _ch(**kw) -> Challenge:
    base = {"name": "x", "description": "d"}
    base.update(kw)
    return Challenge(**base)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "probe.py").write_text("# scratch\n")
    return tmp_path


def test_accept_well_formed_flag(workdir):
    v = check("HTB{real_body_42}", _ch(flag_prefix="HTB"), workdir)
    assert v.verdict == Verdict.ACCEPT


def test_reject_unclosed_brace(workdir):
    # Real case from OT splash-array: `WANLAI{d0f2c4aa536a0d0ab`.
    v = check("WANLAI{d0f2c4aa536a0d0ab", _ch(flag_prefix="WANLAI"), workdir)
    assert v.verdict == Verdict.REJECT
    assert "brace" in v.reason.lower()


def test_reject_wrong_prefix(workdir):
    v = check("flag{got_this_one}", _ch(flag_prefix="HTB"), workdir)
    assert v.verdict == Verdict.REJECT
    assert "prefix" in v.reason.lower()


def test_reject_expected_format_mismatch(workdir):
    v = check(
        "WANLAI{zzz}",
        _ch(expected_format=r"WANLAI\{[0-9a-f]{32}\}"),
        workdir,
    )
    assert v.verdict == Verdict.REJECT
    assert "format" in v.reason.lower()


def test_reject_length_and_control_chars(workdir):
    short = check("x{}", _ch(), workdir)
    assert short.verdict == Verdict.REJECT
    control = check("flag{\x07bell}", _ch(), workdir)
    assert control.verdict == Verdict.REJECT


def test_warn_on_prior_knowledge_log(workdir):
    (workdir / "work" / "prior-knowledge.log").write_text("recalled creds\n")
    v = check("HTB{body}", _ch(flag_prefix="HTB"), workdir)
    assert v.verdict == Verdict.WARN
    assert "prior_knowledge" in v.reason


def test_warn_on_empty_scratch(tmp_path):
    v = check("HTB{body}", _ch(flag_prefix="HTB"), tmp_path)
    assert v.verdict == Verdict.WARN
    assert "no_scratch" in v.reason


def test_reject_beats_warn_when_both_trigger(workdir):
    v = check("not_a_flag", _ch(), workdir)
    assert v.verdict == Verdict.REJECT
