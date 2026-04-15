from pathlib import Path
from hydra.models import Challenge, Result
from hydra.failures import write_failure_md, write_failures_summary

def _mk_result(name="x", status="timeout", reason="wall-clock timeout"):
    return Result(
        name=name, status=status, flag=None,
        duration_s=3600.0, started_at="t0", finished_at="t1",
        worker_exit_code=124, work_dir=f"./runs/{name}/",
        reason=reason,
    )

def test_writes_failure_md(tmp_path: Path):
    c = Challenge(name="x", description="d", category="pwn")
    r = _mk_result("x", "timeout", "timeout after 3600s")
    work_dir = tmp_path / "runs" / "x"
    (work_dir / "logs").mkdir(parents=True)
    (work_dir / "logs" / "claude.stdout.jsonl").write_text(
        "\n".join(f"line {i}" for i in range(100))
    )
    failures_dir = tmp_path / "failures"
    md_path = write_failure_md(c, r, work_dir=work_dir, failures_dir=failures_dir)
    md = md_path.read_text()
    assert "x" in md
    assert "timeout" in md
    assert "line 99" in md  # last 50 lines tail includes recent
    assert "line 50" in md

def test_includes_postmortem(tmp_path: Path):
    c = Challenge(name="x", description="d")
    r = _mk_result("x", "failed", "no flag")
    work_dir = tmp_path / "runs" / "x"
    (work_dir / "logs").mkdir(parents=True)
    (work_dir / "work").mkdir(parents=True)
    (work_dir / "logs" / "claude.stdout.jsonl").write_text("…")
    (work_dir / "work" / "postmortem.md").write_text("tried Wiener, n didn't factor")
    md = write_failure_md(c, r, work_dir=work_dir, failures_dir=tmp_path / "failures").read_text()
    assert "tried Wiener" in md

def test_transcript_fence_escapes_embedded_backticks(tmp_path: Path):
    """A tail containing triple-backticks (e.g., agent stdout showing a
    code block in a tool result) must not prematurely close the
    markdown fence. The outer fence length must exceed any backtick run
    in the embedded content so the rendered .md stays as one code block."""
    c = Challenge(name="x", description="d")
    r = _mk_result("x", "failed", "no flag")
    work_dir = tmp_path / "runs" / "x"
    (work_dir / "logs").mkdir(parents=True)
    (work_dir / "logs" / "claude.stdout.jsonl").write_text(
        "start\n```python\ndef f(): pass\n```\nend\n"
    )
    md = write_failure_md(
        c, r, work_dir=work_dir, failures_dir=tmp_path / "failures",
    ).read_text()
    # Find the fenced tail block. The opening fence must be strictly
    # longer than the max embedded backtick run (3 → fence of 4).
    assert "````" in md
    # The content must appear between two matching 4+ backtick fences.
    # Naive check: there should be exactly 2 fences of length 4 in the
    # tail section, and the triple-backticks inside stay intact.
    assert "```python" in md
    assert md.count("````") >= 2


def test_safe_fence_scales_with_longest_run():
    from hydra.failures import _safe_fence
    assert _safe_fence("no backticks at all") == "```"
    assert _safe_fence("single ` inline") == "```"
    assert _safe_fence("double `` inline") == "```"
    assert _safe_fence("triple ``` is common") == "````"
    assert _safe_fence("a ```` b") == "`````"
    # Empty content still gets the minimum 3-backtick fence.
    assert _safe_fence("") == "```"


def test_summary_table(tmp_path: Path):
    results = [
        _mk_result("a", "timeout", "60m"),
        _mk_result("b", "failed", "no flag"),
    ]
    failures_dir = tmp_path / "failures"
    failures_dir.mkdir()
    write_failures_summary(results, failures_dir=failures_dir)
    s = (failures_dir / "SUMMARY.md").read_text()
    assert "| a" in s
    assert "| b" in s
    assert "timeout" in s
