import json
from pathlib import Path
import pytest
from hydra.normalize import normalize_challenges, NormalizationError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "challenges"

def load(name: str):
    return json.loads((FIXTURES / name).read_text())

def test_minimal():
    [c] = normalize_challenges(load("minimal.json"))
    assert c.name == "baby-rsa"
    assert c.description == "Decrypt this."
    assert c.files == []
    assert c.remote is None

def test_rich():
    [c] = normalize_challenges(load("rich.json"))
    assert c.name == "pwn1"
    assert c.category == "pwn"
    assert c.points == 200
    assert c.files == [Path("/tmp/pwn1-binary")]
    assert c.remote == "nc chal.example.com 1337"
    assert c.hints == ["libc is 2.35"]

def test_unusual_keys():
    [c] = normalize_challenges(load("unusual_keys.json"))
    assert c.name == "web-login"
    assert c.description == "SQL injection somewhere."
    assert c.remote == "http://ctf.example.com:8080"
    assert c.category == "web"
    assert c.points == 100

def test_name_fallback_to_hash():
    raw = [{"description": "no name here"}]
    [c] = normalize_challenges(raw)
    assert c.name.startswith("chal-")
    assert len(c.name) <= 16

def test_id_as_name():
    [c] = normalize_challenges([{"id": "Q42", "description": "x"}])
    assert c.name == "Q42"

def test_task_as_description():
    [c] = normalize_challenges([{"name": "x", "task": "solve it"}])
    assert c.description == "solve it"

def test_hint_singular():
    [c] = normalize_challenges([{"name": "x", "description": "y", "hint": "try harder"}])
    assert c.hints == ["try harder"]

def test_paths_coerced_to_path():
    [c] = normalize_challenges([
        {"name": "x", "description": "y", "paths": ["a.txt", "b.bin"]}
    ])
    assert all(isinstance(p, Path) for p in c.files)
    assert [p.name for p in c.files] == ["a.txt", "b.bin"]

def test_reject_no_desc_no_files():
    with pytest.raises(NormalizationError):
        normalize_challenges([{"name": "x"}])

def test_accept_files_no_description():
    [c] = normalize_challenges([{"name": "x", "files": ["/tmp/a"]}])
    assert c.description == ""
    assert c.files == [Path("/tmp/a")]

def test_unicode_names():
    [c] = normalize_challenges([{"name": "รหัสลับ", "description": "solve"}])
    assert c.name == "รหัสลับ"

def test_whole_file_not_list_fails():
    with pytest.raises(NormalizationError):
        normalize_challenges({"not": "a list"})

def test_empty_list_ok():
    assert normalize_challenges([]) == []

def test_duplicate_names_appended_suffix():
    [a, b] = normalize_challenges([
        {"name": "x", "description": "1"},
        {"name": "x", "description": "2"},
    ])
    assert a.name == "x"
    assert b.name == "x-2"

def test_safe_name_for_workdir():
    from hydra.normalize import safe_name
    assert safe_name("hello world") == "hello-world"
    assert safe_name("a/b") == "a-b"
    assert safe_name("../evil") == "-evil"
    assert safe_name("รหัสลับ") == "รหัสลับ"  # unicode OK
