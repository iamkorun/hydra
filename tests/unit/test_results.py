import json
from pathlib import Path
from hydra.models import Result
from hydra.results import ResultsWriter, load_jsonl_names

def _mk(name, status, flag=None):
    return Result(
        name=name, status=status, flag=flag,
        duration_s=1.0, started_at="t0", finished_at="t1",
        worker_exit_code=0, work_dir=f"./runs/{name}/",
    )

def test_append_jsonl_creates_file(tmp_path: Path):
    w = ResultsWriter(
        jsonl_path=tmp_path / "r.jsonl",
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("a", "solved", "flag{1}"))
    lines = (tmp_path / "r.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["name"] == "a"

def test_flags_json_updates_atomically(tmp_path: Path):
    w = ResultsWriter(
        jsonl_path=tmp_path / "r.jsonl",
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("a", "solved", "flag{A}"))
    w.append(_mk("b", "failed"))
    flags = json.loads((tmp_path / "f.json").read_text())
    assert flags["a"] == "flag{A}"
    assert flags["__failed__"] == ["b"]
    assert "b" not in flags or flags.get("b") is None

def test_finalize_writes_results_json(tmp_path: Path):
    w = ResultsWriter(
        jsonl_path=tmp_path / "r.jsonl",
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("a", "solved", "flag{A}"))
    w.append(_mk("b", "timeout"))
    w.finalize(run_id="run-xyz")
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["run_id"] == "run-xyz"
    assert data["summary"]["total"] == 2
    assert data["summary"]["solved"] == 1
    assert data["summary"]["timeout"] == 1
    assert len(data["challenges"]) == 2

def test_load_jsonl_names_for_resume(tmp_path: Path):
    jsonl = tmp_path / "r.jsonl"
    jsonl.write_text(
        '{"name":"a","status":"solved"}\n{"name":"b","status":"failed"}\n'
    )
    solved, failed = load_jsonl_names(jsonl)
    assert solved == {"a"}
    assert failed == {"b"}

def test_load_jsonl_missing_file(tmp_path: Path):
    solved, failed = load_jsonl_names(tmp_path / "missing.jsonl")
    assert solved == set()
    assert failed == set()


def test_retry_success_removes_name_from_failed_list(tmp_path: Path):
    """When a challenge is retried and succeeds, flags.json must reflect
    only the latest outcome: the name appears under data with its flag
    and NOT under __failed__. Without coalescing by name, the earlier
    failed entry leaks into __failed__ alongside the success."""
    jsonl = tmp_path / "r.jsonl"
    # Simulate a prior failure already persisted to the jsonl.
    jsonl.write_text(json.dumps({
        "name": "x", "status": "failed", "flag": None,
        "duration_s": 1.0, "started_at": "t0", "finished_at": "t1",
        "worker_exit_code": 0, "work_dir": "./runs/x/",
        "reason": "no flag",
    }) + "\n")
    w = ResultsWriter(
        jsonl_path=jsonl,
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("x", "solved", "flag{retry_win}"))

    flags = json.loads((tmp_path / "f.json").read_text())
    assert flags.get("x") == "flag{retry_win}"
    assert "x" not in flags.get("__failed__", [])


def test_init_creates_parent_dirs(tmp_path: Path):
    """A user may point --jsonl / --flags-out / --results at a nested path
    whose parent dir doesn't exist yet. The writer must create those dirs
    so the first append() doesn't crash with FileNotFoundError."""
    nested = tmp_path / "a" / "b" / "c"
    assert not nested.exists()
    w = ResultsWriter(
        jsonl_path=nested / "r.jsonl",
        flags_path=nested / "f.json",
        results_path=nested / "r.json",
    )
    w.append(_mk("x", "solved", "flag{x}"))
    assert (nested / "r.jsonl").exists()
    assert (nested / "f.json").exists()


def test_init_tolerates_malformed_jsonl_lines(tmp_path: Path):
    """Schema drift or partial writes shouldn't block resume. Bad lines
    are skipped; good ones are loaded."""
    jsonl = tmp_path / "r.jsonl"
    jsonl.write_text(
        "not json at all\n"
        '{"name": "x", "status": "solved", "flag": "flag{ok}", "duration_s": 1.0, '
        '"started_at": "s", "finished_at": "f", "worker_exit_code": 0, '
        '"work_dir": "."}\n'
        '{"name": "y", "extra_field_from_future_version": true}\n'
    )
    w = ResultsWriter(
        jsonl_path=jsonl,
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    names = {r.name for r in w._results}
    assert "x" in names
    # The malformed and schema-drifted lines are silently skipped.
    assert "y" not in names


def test_finalize_coalesces_duplicate_names(tmp_path: Path):
    """Summary counts must reflect the latest per-name outcome, not the
    raw jsonl sequence. A challenge that went failed → solved must be
    counted once as solved, not once failed and once solved."""
    jsonl = tmp_path / "r.jsonl"
    jsonl.write_text(json.dumps({
        "name": "x", "status": "failed", "flag": None,
        "duration_s": 1.0, "started_at": "t0", "finished_at": "t1",
        "worker_exit_code": 0, "work_dir": "./runs/x/",
        "reason": "no flag",
    }) + "\n")
    w = ResultsWriter(
        jsonl_path=jsonl,
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("x", "solved", "flag{retry_win}"))
    w.finalize(run_id="run-1")

    data = json.loads((tmp_path / "r.json").read_text())
    assert data["summary"]["total"] == 1
    assert data["summary"]["solved"] == 1
    assert data["summary"]["failed"] == 0
    assert len(data["challenges"]) == 1
