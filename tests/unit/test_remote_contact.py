import json
from pathlib import Path

from hydra.remote_contact import parse_remote, was_remote_contacted


def test_parse_remote_bare_host_port():
    assert parse_remote("198.51.100.82:32300") == ("198.51.100.82", 32300)


def test_parse_remote_http_url():
    assert parse_remote("http://198.51.100.73:31277") == ("198.51.100.73", 31277)


def test_parse_remote_http_url_with_path():
    assert parse_remote("http://198.51.100.73:31277/app") == ("198.51.100.73", 31277)


def test_parse_remote_hostname_only():
    assert parse_remote("example.com") == ("example.com", None)


def test_parse_remote_none_returns_none():
    assert parse_remote(None) == (None, None)


def _fake_log(tmp_path: Path, assistant_messages: list[dict]) -> Path:
    f = tmp_path / "claude.stdout.jsonl"
    with f.open("w") as fh:
        for msg in assistant_messages:
            fh.write(json.dumps(msg) + "\n")
    return f


def test_was_contacted_no_log_file(tmp_path: Path):
    # No log yet — default to trusting (don't demote on missing evidence).
    missing = tmp_path / "nope.jsonl"
    assert was_remote_contacted(missing, "198.51.100.82:32300") is True


def test_was_contacted_no_remote_returns_true(tmp_path: Path):
    log = _fake_log(tmp_path, [])
    assert was_remote_contacted(log, None) is True
    assert was_remote_contacted(log, "") is True


def test_was_contacted_host_in_bash(tmp_path: Path):
    log = _fake_log(tmp_path, [{
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "curl -sI http://198.51.100.82:32300/"},
        }]},
    }])
    assert was_remote_contacted(log, "198.51.100.82:32300") is True


def test_was_contacted_port_only_is_enough(tmp_path: Path):
    # Agent might use `$HOST` var and the port literal — still counts.
    log = _fake_log(tmp_path, [{
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "nc $HOST 32300"},
        }]},
    }])
    assert was_remote_contacted(log, "198.51.100.82:32300") is True


def test_not_contacted_empty_log(tmp_path: Path):
    log = _fake_log(tmp_path, [])
    assert was_remote_contacted(log, "198.51.100.82:32300") is False


def test_not_contacted_unrelated_bash(tmp_path: Path):
    log = _fake_log(tmp_path, [{
        "type": "assistant",
        "message": {"content": [{
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "gcc -O3 solve.c -o solve"},
        }]},
    }])
    assert was_remote_contacted(log, "198.51.100.82:32300") is False
