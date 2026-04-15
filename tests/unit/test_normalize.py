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


def test_duplicate_names_skip_existing_suffix():
    """Raw input may already contain the suffix we'd generate. The de-dup
    loop must skip any candidate that's already taken so no two challenges
    share a name (and therefore a workdir)."""
    out = normalize_challenges([
        {"name": "foo", "description": "1"},
        {"name": "foo-2", "description": "2"},
        {"name": "foo", "description": "3"},
        {"name": "foo", "description": "4"},
    ])
    names = [c.name for c in out]
    assert names == ["foo", "foo-2", "foo-3", "foo-4"]
    assert len(set(names)) == len(names)


def test_non_string_file_path_raises_clear_error():
    """Malformed input where a file path is not a string must surface a
    NormalizationError with the entry index, not an opaque TypeError."""
    with pytest.raises(NormalizationError, match="entry #0.*file path must be a string"):
        normalize_challenges([{"name": "x", "description": "y", "files": [1, 2]}])
    with pytest.raises(NormalizationError, match="entry #1.*file path must be a string"):
        normalize_challenges([
            {"name": "ok", "description": "y", "files": ["/tmp/a"]},
            {"name": "bad", "description": "y", "files": [{"nested": "object"}]},
        ])


def test_duplicate_names_many_collisions():
    """Monotonic suffix counter must keep climbing even when raw input
    contains a mix of 'x' and 'x-N' forms."""
    out = normalize_challenges([
        {"name": "x", "description": "a"},
        {"name": "x", "description": "b"},   # -> x-2
        {"name": "x-3", "description": "c"}, # raw
        {"name": "x", "description": "d"},   # -> x-4 (skip x-3)
        {"name": "x", "description": "e"},   # -> x-5
    ])
    names = [c.name for c in out]
    assert names == ["x", "x-2", "x-3", "x-4", "x-5"]

def test_safe_name_for_workdir():
    from hydra.normalize import safe_name
    assert safe_name("hello world") == "hello-world"
    assert safe_name("a/b") == "a-b"
    assert safe_name("../evil") == "-evil"
    assert safe_name("รหัสลับ") == "รหัสลับ"  # unicode OK


def test_normalize_applies_safe_name_to_prevent_path_traversal():
    """Challenge names become directory names (runs/<name>/), so raw input
    must be sanitized at normalization time. Without this, a malicious or
    careless input like '../evil' would escape the runs directory."""
    [c] = normalize_challenges([{"name": "../evil", "description": "x"}])
    assert c.name == "-evil"
    assert "/" not in c.name
    assert ".." not in c.name

    [c] = normalize_challenges([{"name": "a/b/c", "description": "x"}])
    assert c.name == "a-b-c"

    [c] = normalize_challenges([{"name": "with spaces", "description": "x"}])
    assert c.name == "with-spaces"

    [c] = normalize_challenges([{"name": "back\\slash", "description": "x"}])
    assert c.name == "back-slash"
