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

def test_regex_fallback(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "some output contains CTF{buried}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "CTF{buried}"

def test_no_flag_returns_none(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="no flag here")
    assert flag is None

def test_flag_file_missing_ok(tmp_path: Path):
    # Treat missing file as empty — fall through.
    stdout = "FLAG: flag{ok}"
    flag = extract_flag(flag_file=tmp_path / "nope.txt", stdout=stdout)
    assert flag == "flag{ok}"

def test_multiple_flags_take_most_specific_last(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "early CTF{first}\nlater flag{winner}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{winner}"

def test_uppercase_flag(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG{SHOUTY}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "FLAG{SHOUTY}"

def test_custom_prefix(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "the answer is picoCTF{pic0_flag}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "picoCTF{pic0_flag}"

def test_whitespace_stripped_from_file(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("  flag{trim}  \n\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag == "flag{trim}"

def test_last_flag_line_wins(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: flag{early}\nactually FLAG: flag{late}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{late}"

def test_nested_braces_ok(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    # Spec regex stops at first `}` — the flag format doesn't nest.
    stdout = "flag{inner}extra}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    # File empty, stdout has flag after — should find flag{inner}
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{inner}"
