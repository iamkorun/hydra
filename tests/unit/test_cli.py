import json
import sys
from pathlib import Path
import pytest
from hydra.cli import build_parser, resolve_config

def test_parser_defaults():
    p = build_parser()
    ns = p.parse_args(["chal.json"])
    assert ns.challenges == "chal.json"
    assert ns.parallel == 8
    assert ns.timeout == 3600
    assert ns.model == "claude-opus-4-6"
    assert ns.retry_failed is False
    assert ns.only is None

def test_parser_overrides():
    p = build_parser()
    ns = p.parse_args([
        "-",
        "--parallel", "4",
        "--timeout", "600",
        "--model", "claude-haiku-4-5",
        "--retry-failed",
        "--only", "a,b,c",
    ])
    assert ns.challenges == "-"
    assert ns.parallel == 4
    assert ns.timeout == 600
    assert ns.model == "claude-haiku-4-5"
    assert ns.retry_failed is True
    assert ns.only == "a,b,c"

def test_resolve_config_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    with pytest.raises(SystemExit):
        resolve_config(ns, root=tmp_path)

def test_resolve_config_uses_env_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xyz")
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.api_key == "sk-xyz"
    assert cfg.parallel == 8
    assert cfg.runs_dir == tmp_path / "runs"
    assert cfg.failures_dir == tmp_path / "failures"

def test_only_filter_applies(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    ns = build_parser().parse_args([str(tmp_path / "x.json"), "--only", "a,c"])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.only_filter == {"a", "c"}
