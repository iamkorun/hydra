import asyncio
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
    # Clean exit, no flag recovered → status "failed"
    return WorkerResult(
        name=kwargs["name"], exit_code=0,
        stdout="no flag found\n",
        stderr="", timed_out=False, duration_s=0.1,
    )

async def fake_worker_errored(*args, **kwargs) -> WorkerResult:
    # Non-zero exit → status "error"
    return WorkerResult(
        name=kwargs["name"], exit_code=1,
        stdout="partial output\n",
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

async def test_failed_status_on_clean_exit_no_flag(tmp_path, monkeypatch):
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
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()

async def test_error_status_on_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_errored)
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
    assert r.status == "error"
    assert r.flag is None
    # stderr preserved in reason for debugging
    assert "boom" in (r.reason or "")
    assert (tmp_path / "failures" / "a.md").exists()

async def test_passk_first_flag_wins(tmp_path, monkeypatch):
    """pass@k: fastest attempt to produce a flag wins; siblings cancelled."""
    cancelled = {"count": 0}
    order = {"idx": 0}

    async def race_worker(*args, **kwargs):
        my_idx = order["idx"]
        order["idx"] += 1
        try:
            if my_idx == 0:
                await asyncio.sleep(0.01)  # fastest → winner
                # Write flag to the real workdir so extract_flag can find it.
                (kwargs["workdir"] / "flag.txt").write_text(f"flag{{win-{my_idx}}}\n")
                return WorkerResult(
                    name=kwargs["name"], exit_code=0,
                    stdout=f"FLAG: flag{{win-{my_idx}}}\n",
                    stderr="", timed_out=False, duration_s=0.01,
                )
            await asyncio.sleep(5)  # siblings should be cancelled before this
            return WorkerResult(
                name=kwargs["name"], exit_code=0,
                stdout="slow\n", stderr="", timed_out=False, duration_s=5.0,
            )
        except asyncio.CancelledError:
            cancelled["count"] += 1
            raise

    monkeypatch.setattr("hydra.orchestrator.run_worker", race_worker)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=3, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        attempts=3,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "solved"
    assert r.flag == "flag{win-0}"
    # The two losing siblings should have been cancelled.
    assert cancelled["count"] == 2
    # Winner's flag copied to the top-level conventional path.
    assert (tmp_path / "runs" / "a" / "flag.txt").read_text().strip() == "flag{win-0}"

async def test_passk_all_fail(tmp_path, monkeypatch):
    """pass@k: if every attempt fails, result is failed with the last worker's state."""
    async def no_flag(*args, **kwargs):
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="tried but no flag\n", stderr="",
            timed_out=False, duration_s=0.05,
        )
    monkeypatch.setattr("hydra.orchestrator.run_worker", no_flag)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=2, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        attempts=2,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
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
