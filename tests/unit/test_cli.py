import asyncio
import json
from pathlib import Path

import pytest
from hydra.cli import ResolvedConfig, build_parser, resolve_config, _run, _compute_skips


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
    assert ns.parallel is None
    assert ns.timeout == 3600
    assert ns.model == "claude-opus-4-7"
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


def test_only_filter_normalizes_to_safe_name(monkeypatch, tmp_path):
    """Challenge names are sanitized by safe_name at normalize time. The
    --only filter must apply the same transform so a user who passes the
    raw JSON name (e.g. 'foo bar') still matches the stored 'foo-bar'."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    _patch_default_creds(monkeypatch, tmp_path, exists=False, logged_in=False)
    ns = build_parser().parse_args([
        str(tmp_path / "x.json"),
        "--only", "foo bar, baz/qux",
    ])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.only_filter == {"foo-bar", "baz-qux"}


def test_default_out_dir_from_json_stem(tmp_path):
    from hydra.cli import _default_out_dir
    # Filename → cwd/<stem>/ so back-to-back runs don't collide.
    assert _default_out_dir("phase-1.json", tmp_path) == tmp_path / "phase-1"
    assert _default_out_dir("/abs/path/phase-2.json", tmp_path) == tmp_path / "phase-2"
    # Stdin has no filename → fall back to cwd (caller's problem to segregate).
    assert _default_out_dir("-", tmp_path) == tmp_path


def test_resolve_parallel_defaults_to_challenge_count():
    from hydra.cli import _resolve_parallel
    # Unspecified: fan out to every challenge.
    assert _resolve_parallel(None, 5) == 5
    # Empty JSON: floor at 1 so asyncio.Semaphore doesn't deadlock.
    assert _resolve_parallel(None, 0) == 1
    # Explicit user value wins, even if it exceeds the challenge count
    # (harmless — semaphore just won't saturate).
    assert _resolve_parallel(4, 10) == 4
    assert _resolve_parallel(20, 3) == 20


def test_only_filter_empty_string_returns_none():
    from hydra.cli import _parse_only
    assert _parse_only(None) is None
    assert _parse_only("") is None
    assert _parse_only("   ") is None
    # Trailing/empty commas are dropped.
    assert _parse_only("a,,b,") == {"a", "b"}


def _mk_resolved(tmp_path: Path, **overrides) -> ResolvedConfig:
    base = {
        "challenges_path": str(tmp_path / "chal.json"),
        "parallel": 1,
        "timeout": 5,
        "model": "m",
        "runs_dir": tmp_path / "runs",
        "results_path": tmp_path / "results.json",
        "jsonl_path": tmp_path / "results.jsonl",
        "flags_path": tmp_path / "flags.json",
        "failures_dir": tmp_path / "failures",
        "retry_failed": False,
        "only_filter": None,
        "dry_run": True,
        "rebuild_image": False,
        "api_key": "sk",
    }
    base.update(overrides)
    return ResolvedConfig(**base)


def test_run_returns_2_when_only_filter_matches_nothing(tmp_path, capsys):
    """A typo'd --only should not silently run zero challenges."""
    (tmp_path / "chal.json").write_text(json.dumps([
        {"name": "alpha", "description": "x"},
        {"name": "beta", "description": "y"},
    ]))
    cfg = _mk_resolved(tmp_path, only_filter={"does-not-exist"})
    rc = asyncio.run(_run(cfg))
    assert rc == 2
    err = capsys.readouterr().err
    assert "does-not-exist" in err
    assert "alpha" in err  # lists available names


def test_run_dry_run_with_matching_only_returns_0(tmp_path):
    (tmp_path / "chal.json").write_text(json.dumps([
        {"name": "alpha", "description": "x"},
        {"name": "beta", "description": "y"},
    ]))
    cfg = _mk_resolved(tmp_path, only_filter={"alpha"})
    assert asyncio.run(_run(cfg)) == 0


def test_compute_skips_resume_semantics(tmp_path):
    """By default, resume skips both solved AND failed so we don't re-burn
    budget on hopeless ones. With --retry-failed, the skip set drops the
    failed entries so they get another attempt."""
    jsonl = tmp_path / "r.jsonl"
    jsonl.write_text(
        '{"name":"a","status":"solved"}\n'
        '{"name":"b","status":"failed"}\n'
        '{"name":"c","status":"timeout"}\n'
        '{"name":"d","status":"error"}\n'
    )
    cfg_no_retry = _mk_resolved(tmp_path, jsonl_path=jsonl, retry_failed=False)
    assert _compute_skips(cfg_no_retry) == {"a", "b", "c", "d"}

    cfg_retry = _mk_resolved(tmp_path, jsonl_path=jsonl, retry_failed=True)
    assert _compute_skips(cfg_retry) == {"a"}


def test_compute_skips_missing_jsonl(tmp_path):
    """First run: no jsonl exists → nothing to skip."""
    cfg = _mk_resolved(tmp_path, jsonl_path=tmp_path / "nope.jsonl")
    assert _compute_skips(cfg) == set()


def test_prompt_volumes_resolve_against_hydra_repo_not_cwd(monkeypatch, tmp_path):
    """Prompt volumes must point at the hydra checkout (where CLAUDE.md /
    .claude / exploits ship as agent assets), not the user's cwd. Using
    cwd let docker auto-create empty host dirs at every missing source,
    silently mounting an empty `/workspace/CLAUDE.md` directory inside
    the container — the inner agent then read EISDIR, lost the system
    prompt, and lost every specialist agent definition."""
    from hydra.cli import _hydra_repo_root, _prompt_volumes

    # Pretend the user runs hydra from somewhere with no CLAUDE.md.
    monkeypatch.chdir(tmp_path)
    vols = _prompt_volumes()
    repo = _hydra_repo_root()

    # All sources point at the hydra checkout, not cwd.
    for src in vols:
        assert src.is_relative_to(repo), (src, repo)
        assert not src.is_relative_to(tmp_path)

    # And the three canonical asset paths are present.
    by_dest = {dest: src for src, dest in vols.items()}
    assert by_dest["/workspace/CLAUDE.md"] == repo / "CLAUDE.md"
    assert by_dest["/workspace/.claude"] == repo / ".claude"
    assert by_dest["/workspace/exploits"] == repo / "exploits"


def test_run_returns_2_on_normalization_error(tmp_path, capsys):
    (tmp_path / "chal.json").write_text(json.dumps([{"name": "x"}]))  # no desc, no files
    cfg = _mk_resolved(tmp_path)
    rc = asyncio.run(_run(cfg))
    assert rc == 2
    assert "error" in capsys.readouterr().err
