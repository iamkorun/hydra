import json
from pathlib import Path

from hydra.models import Challenge
from hydra.orchestrator import Orchestrator, OrchestratorConfig
from hydra.results import ResultsWriter


async def _run(root: Path, scenario_path: Path, scenario: dict, *, parallel=1):
    scenario_path.write_text(json.dumps(scenario))

    (root / "runs").mkdir(exist_ok=True)
    writer = ResultsWriter(
        jsonl_path=root / "results.jsonl",
        flags_path=root / "flags.json",
        results_path=root / "results.json",
    )
    cfg = OrchestratorConfig(
        parallel=parallel,
        timeout_s=5,
        model="m",
        image="hydra-worker",
        api_key="sk",
        runs_dir=root / "runs",
        failures_dir=root / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    return writer, orch


async def test_happy_path(tmp_path, fake_docker):
    writer, orch = await _run(
        tmp_path,
        fake_docker,
        {"a": {"stdout": "working\nFLAG: flag{a_ok}\n", "exit_code": 0}},
    )
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer._results
    assert r.status == "solved"
    assert r.flag == "flag{a_ok}"
    flags = json.loads((tmp_path / "flags.json").read_text())
    assert flags["a"] == "flag{a_ok}"


async def test_failed_no_flag(tmp_path, fake_docker):
    writer, orch = await _run(
        tmp_path,
        fake_docker,
        {"a": {"stdout": "nothing to see\n", "exit_code": 0}},
    )
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer._results
    assert r.status == "failed"
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()


async def test_flag_file_only(tmp_path, fake_docker):
    writer, orch = await _run(
        tmp_path,
        fake_docker,
        {"a": {"stdout": "", "flag_file": "flag{from_file}\n", "exit_code": 0}},
    )
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer._results
    assert r.status == "solved"
    assert r.flag == "flag{from_file}"


async def test_mixed_batch(tmp_path, fake_docker):
    writer, orch = await _run(
        tmp_path,
        fake_docker,
        {
            "a": {"stdout": "FLAG: flag{a}", "exit_code": 0},
            "b": {"stdout": "boom\n", "stderr": "explode", "exit_code": 1},
            "c": {"stdout": "", "flag_file": "CTF{c_ok}"},
        },
        parallel=3,
    )
    await orch.run(
        [
            Challenge(name="a", description="x"),
            Challenge(name="b", description="x"),
            Challenge(name="c", description="x"),
        ]
    )
    by_name = {r.name: r for r in writer._results}
    assert by_name["a"].status == "solved"
    # Non-zero exit → "error" (distinct from "failed" which is clean-exit-no-flag)
    assert by_name["b"].status == "error"
    assert "explode" in (by_name["b"].reason or "")
    assert by_name["c"].status == "solved"
