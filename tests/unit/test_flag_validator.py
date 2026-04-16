from hydra.flag_validator import validate, Verdict

def test_accept_real_flag():
    v = validate("HTB{4n_unusual_s1ght1ng_1n_SSH_l0gs!}")
    assert v.verdict == Verdict.ACCEPT
    assert v.reason is None

def test_reject_malformed_no_braces():
    v = validate("not_a_flag")
    assert v.verdict == Verdict.REJECT

def test_reject_whitespace_body():
    v = validate("HTB{with space inside}")
    assert v.verdict == Verdict.REJECT
    assert "whitespace" in v.reason

def test_reject_too_long_body():
    v = validate("HTB{" + "a" * 200 + "}")
    assert v.verdict == Verdict.REJECT
    assert "length" in v.reason

def test_reject_banned_phrase():
    v = validate("HTB{REMINDER: read the docs}")
    assert v.verdict == Verdict.REJECT

def test_warn_placeholder_body():
    for body in ("test", "example", "FIXME", "placeholder", "fake", "REDACTED"):
        v = validate(f"flag{{{body}}}")
        assert v.verdict == Verdict.WARN, f"{body} should WARN"

def test_warn_prefix_mismatch():
    v = validate(
        "flag{got_this_one}",
        expected_prefix="HTB",
    )
    assert v.verdict == Verdict.WARN
    assert "prefix" in v.reason

def test_accept_when_prefix_matches():
    v = validate(
        "HTB{real}",
        expected_prefix="HTB",
    )
    assert v.verdict == Verdict.ACCEPT
