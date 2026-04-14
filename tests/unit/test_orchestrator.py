import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pytest
from hydra.models import Challenge, Result
from hydra.orchestrator import Orchestrator, OrchestratorConfig
from hydra.docker_worker import WorkerResult

class FakeWriter:
    def __init__(self):
        self.appended: list[Result] = []
        self.finalized = False
    def append(self, r): self.appended.append(r)
    def finalize(self, *, run_id): self.finalized = True

async def fake_worker_solved(*args, **kwargs) -> WorkerResult:
    return WorkerResult(
        name=kwargs["name"], exit_code=0,
        stdout=f"FLAG: flag{{{kwargs['name']}}}\n",
        stderr="", timed_out=False, duration_s=0.1,
    )

async def fake_worker_failed(*args, **kwargs) -> WorkerResult:
    return WorkerResult(
        name=kwargs["name"], exit_code=1,
        stdout="no flag found\n",
        stderr="boom", timed_out=False, duration_s=0.1,
    )

async def fake_worker_timeout(*args, **kwargs) -> WorkerResult:
    return WorkerResult(
        name=kwargs["name"], exit_code=-9,
        stdout="", stderr="",
        timed_out=True, duration_s=60.0,
    )

async def test_solve_batch(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_solved)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=2, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    challenges = [
        Challenge(name="a", description="x"),
        Challenge(name="b", description="y"),
    ]
    orch = Orchestrator(cfg, writer=writer)
    await orch.run(challenges)
    names = sorted(r.name for r in writer.appended)
    assert names == ["a", "b"]
    assert all(r.status == "solved" for r in writer.appended)
    assert all(r.flag and "flag{" in r.flag for r in writer.appended)

async def test_respects_parallel_semaphore(tmp_path, monkeypatch):
    concurrent = {"count": 0, "max": 0}
    async def slow_worker(*args, **kwargs):
        concurrent["count"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["count"])
        await asyncio.sleep(0.05)
        concurrent["count"] -= 1
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout=f"FLAG: flag{{{kwargs['name']}}}", stderr="",
            timed_out=False, duration_s=0.05,
        )
    monkeypatch.setattr("hydra.orchestrator.run_worker", slow_worker)
    cfg = OrchestratorConfig(
        parallel=2, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    challenges = [Challenge(name=f"c{i}", description="x") for i in range(5)]
    orch = Orchestrator(cfg, writer=FakeWriter())
    await orch.run(challenges)
    assert concurrent["max"] <= 2

async def test_timeout_status(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_timeout)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=1, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "timeout"
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()

async def test_failure_writes_md(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_failed)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "failed"
    assert (tmp_path / "failures" / "a.md").exists()

async def test_skip_already_solved(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_solved)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        skip_names={"a"},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x"), Challenge(name="b", description="y")])
    names = [r.name for r in writer.appended]
    assert names == ["b"]
