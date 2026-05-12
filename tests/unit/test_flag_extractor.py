from pathlib import Path
from hydra.flag_extractor import extract_flag

def test_flag_file_preferred(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("flag{from_file}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="flag{from_stdout}")
    assert flag == "flag{from_file}"

def test_fallback_to_stdout_line(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "working...\nFLAG: flag{via_line}\nbye"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{via_line}"

def test_no_flag_returns_none(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="no flag here")
    assert flag is None

def test_flag_file_missing_ok(tmp_path: Path):
    # Treat missing file as empty — fall through.
    stdout = "FLAG: flag{ok}"
    flag = extract_flag(flag_file=tmp_path / "nope.txt", stdout=stdout)
    assert flag == "flag{ok}"

def test_whitespace_stripped_from_file(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("  flag{trim}  \n\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag == "flag{trim}"

def test_last_flag_line_wins(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: flag{early}\nactually FLAG: flag{late}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{late}"

def test_reject_flag_with_whitespace_in_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "HTB{. To make reading easier, the view is switched}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_flag_with_newline_in_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "HTB{first\nsecond}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_flag_longer_than_cap(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    body = "a" * 200
    stdout = f"HTB{{{body}}}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_flag_with_banned_phrase(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "HTB{REMINDER: You MUST include the sources above}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_flag_with_url_in_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "HTB{see https://hackthebox.com/writeup}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_accept_realistic_htb_flag(tmp_path: Path):
    # Regression: flag body with apostrophe, leet-speak, '!!', and a
    # 32-hex suffix — exercises the realistic-shape acceptance path.
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: HTB{th15_1s_4_pl4us1bl3_l0ng_fl4g_w1th_punctu4t10n!!_0123456789abcdef0123456789abcdef}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{th15_1s_4_pl4us1bl3_l0ng_fl4g_w1th_punctu4t10n!!_0123456789abcdef0123456789abcdef}"

# Phase-4 false-positive regressions.

def test_reject_all_dots_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "format: HTB{...}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_placeholder_fake_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "strings output: HTB{FakeFlagForTesting}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_placeholder_ignore_body(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "decoy: HTB{FlagForPreviousChallengePleaseIgnore}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_reject_placeholder_in_flag_file(tmp_path: Path):
    # Even if written to flag.txt, a placeholder-body flag is rejected.
    (tmp_path / "flag.txt").write_text("HTB{placeholder_value}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag is None

def test_accept_realistic_short_flag_with_digits(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: HTB{a1B2c3}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{a1B2c3}"

def test_accept_real_htb_underscored_flag(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: HTB{4n_und3rsc0r3d_b0dy_w1th_excl4m4t10n!}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{4n_und3rsc0r3d_b0dy_w1th_excl4m4t10n!}"

def test_accept_single_word_training_flag(tmp_path: Path):
    # Regression: easy/training challenges do have single-word flags.
    # Make sure we don't overfit phase-4 by rejecting `picoCTF{welcome}`.
    (tmp_path / "flag.txt").write_text("picoCTF{welcome}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag == "picoCTF{welcome}"

def test_regex_sweep_no_longer_accepts_bare_stdout(tmp_path: Path):
    # flag.txt empty, no `FLAG:` line — stdout contains HTB{...} only in
    # prose. Must return None (a recurring false-positive failure mode).
    (tmp_path / "flag.txt").write_text("")
    stdout = "Challenge README says: format is HTB{real_flag_here}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_regex_sweep_no_longer_accepts_fstring_leak(tmp_path: Path):
    # Python f-string source-code literal leaked via `cat script.py`.
    (tmp_path / "flag.txt").write_text("")
    stdout = "printing: bit{bit_idx} sample={s}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_regex_sweep_no_longer_accepts_binary_strings(tmp_path: Path):
    # `strings ./challenge/binary` leaked a hardcoded decoy into stdout.
    # Decoy contains digits so `fake` substring wouldn't catch it — only
    # the architectural "no sweep" fix saves us here.
    (tmp_path / "flag.txt").write_text("")
    stdout = "strings: HTB{n0_leak_f0r_y0u_1234567890abcdef}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag is None

def test_flag_line_still_works(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "working...\nFLAG: HTB{fr0m_l1ne_echo}\nbye"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "HTB{fr0m_l1ne_echo}"

def test_flag_file_still_works(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("HTB{fr0m_file}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="HTB{wrong}")
    assert flag == "HTB{fr0m_file}"

def test_empty_file_no_flag_line_returns_none(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag is None
