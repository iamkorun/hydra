from pathlib import Path
import pytest
from hydra.cli import build_parser, resolve_config


def _patch_default_creds(monkeypatch, tmp_path, *, exists: bool, logged_in: bool):
    """Point DEFAULT_CREDENTIALS_DIR at a tmp_path and control its state."""
    fake = tmp_path / "fake_home" / ".claude"
    if exists:
        fake.mkdir(parents=True)
        if logged_in:
            (fake / "credentials.json").write_text("{}")
    monkeypatch.setattr("hydra.cli.DEFAULT_CREDENTIALS_DIR", fake)


def test_parser_defaults():
    p = build_parser()
    ns = p.parse_args(["chal.json"])
    assert ns.challenges == "chal.json"
    assert ns.parallel == 8
    assert ns.timeout == 3600
    assert ns.model == "claude-opus-4-6"
    assert ns.retry_failed is False
    assert ns.only is None
    assert ns.credentials_dir is None
    assert ns.use_api_key is False


def test_parser_overrides():
    p = build_parser()
    ns = p.parse_args([
        "-",
        "--parallel", "4",
        "--timeout", "600",
        "--model", "claude-haiku-4-5",
        "--retry-failed",
        "--only", "a,b,c",
        "--credentials-dir", "/tmp/creds",
        "--use-api-key",
    ])
    assert ns.challenges == "-"
    assert ns.parallel == 4
    assert ns.timeout == 600
    assert ns.model == "claude-haiku-4-5"
    assert ns.retry_failed is True
    assert ns.only == "a,b,c"
    assert ns.credentials_dir == "/tmp/creds"
    assert ns.use_api_key is True


def test_resolve_no_auth_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _patch_default_creds(monkeypatch, tmp_path, exists=False, logged_in=False)
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    with pytest.raises(SystemExit):
        resolve_config(ns, root=tmp_path)


def test_resolve_falls_back_to_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xyz")
    _patch_default_creds(monkeypatch, tmp_path, exists=False, logged_in=False)
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.api_key == "sk-xyz"
    assert cfg.credentials_dir is None


def test_resolve_prefers_credentials_when_both(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xyz")
    _patch_default_creds(monkeypatch, tmp_path, exists=True, logged_in=True)
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.credentials_dir is not None
    assert cfg.credentials_dir.name == ".claude"
    assert cfg.api_key == "sk-xyz"  # kept as fallback


def test_resolve_explicit_credentials_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    explicit = tmp_path / "my_creds"
    explicit.mkdir()
    ns = build_parser().parse_args([
        str(tmp_path / "x.json"),
        "--credentials-dir", str(explicit),
    ])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.credentials_dir == explicit


def test_resolve_credentials_dir_missing_errors(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ns = build_parser().parse_args([
        str(tmp_path / "x.json"),
        "--credentials-dir", str(tmp_path / "nope"),
    ])
    with pytest.raises(SystemExit):
        resolve_config(ns, root=tmp_path)


def test_resolve_use_api_key_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xyz")
    _patch_default_creds(monkeypatch, tmp_path, exists=True, logged_in=True)
    ns = build_parser().parse_args([
        str(tmp_path / "x.json"),
        "--use-api-key",
    ])
    cfg = resolve_config(ns, root=tmp_path)
    # --use-api-key forces api-key mode, ignoring available credentials
    assert cfg.credentials_dir is None
    assert cfg.api_key == "sk-xyz"


def test_resolve_use_api_key_without_env_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _patch_default_creds(monkeypatch, tmp_path, exists=True, logged_in=True)
    ns = build_parser().parse_args([
        str(tmp_path / "x.json"),
        "--use-api-key",
    ])
    with pytest.raises(SystemExit):
        resolve_config(ns, root=tmp_path)


def test_only_filter_applies(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    _patch_default_creds(monkeypatch, tmp_path, exists=False, logged_in=False)
    ns = build_parser().parse_args([str(tmp_path / "x.json"), "--only", "a,c"])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.only_filter == {"a", "c"}
