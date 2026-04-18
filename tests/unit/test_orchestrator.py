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
    # Drop a scratch file so the flag_gate's no_scratch WARN rule doesn't
    # fire and demote these "solved" cases to "solved_uncertain".
    wd = kwargs.get("workdir")
    if wd is not None:
        (wd / "work").mkdir(parents=True, exist_ok=True)
        (wd / "work" / "derivation.txt").write_text("solver steps\n")
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
        watchdog=None,
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
        watchdog=None,
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
        watchdog=None,
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
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()

async def test_usage_is_parsed_from_transcript_into_result(tmp_path, monkeypatch):
    """Orchestrator must parse the Claude transcript after each run and
    attach Usage (tokens + cost) to the Result — without this, results.json
    can't answer 'how much did this batch cost'."""
    import json as _json

    async def worker_writing_transcript(*args, **kwargs):
        wd = kwargs["workdir"]
        logs = wd / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "claude.stdout.jsonl").write_text(
            _json.dumps({
                "type": "result", "subtype": "success",
                "total_cost_usd": 0.42,
                "usage": {"input_tokens": 10, "output_tokens": 69,
                          "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 50000},
            }) + "\n"
        )
        # Populate scratch so flag_gate accepts (no_scratch WARN rule).
        (wd / "work").mkdir(parents=True, exist_ok=True)
        (wd / "work" / "derivation.txt").write_text("solver steps\n")
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout=f"FLAG: flag{{{kwargs['name']}}}\n", stderr="",
            timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr(
        "hydra.orchestrator.run_worker", worker_writing_transcript
    )
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "solved"
    assert r.usage.cost_usd == 0.42
    assert r.usage.input_tokens == 10
    assert r.usage.output_tokens == 69
    assert r.usage.cache_creation_input_tokens == 50000


async def test_error_status_on_nonzero_exit(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_errored)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
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
                wd = kwargs["workdir"]
                (wd / "flag.txt").write_text(f"flag{{win-{my_idx}}}\n")
                # Populate scratch so flag_gate doesn't WARN on empty work/.
                (wd / "work").mkdir(parents=True, exist_ok=True)
                (wd / "work" / "derivation.txt").write_text("solver steps\n")
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
        watchdog=None,
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

async def test_passk_winner_with_stdout_only_flag(tmp_path, monkeypatch):
    """pass@k: winning attempt may recover the flag only from stdout (empty
    flag.txt). The canonical top-level flag.txt must still be populated with
    the extracted flag, not an empty string copied from the winner's file."""
    order = {"idx": 0}

    async def race_worker(*args, **kwargs):
        my_idx = order["idx"]
        order["idx"] += 1
        if my_idx == 0:
            # Winner: leave flag.txt untouched (empty), flag only in stdout.
            wd = kwargs["workdir"]
            # Populate scratch so flag_gate doesn't WARN on empty work/.
            (wd / "work").mkdir(parents=True, exist_ok=True)
            (wd / "work" / "derivation.txt").write_text("solver steps\n")
            return WorkerResult(
                name=kwargs["name"], exit_code=0,
                stdout=f"FLAG: flag{{stdout-only-{my_idx}}}\n",
                stderr="", timed_out=False, duration_s=0.01,
            )
        await asyncio.sleep(5)  # sibling, should be cancelled
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="slow\n", stderr="", timed_out=False, duration_s=5.0,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", race_worker)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=2, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        attempts=2,
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "solved"
    assert r.flag == "flag{stdout-only-0}"
    # Canonical top-level flag.txt must contain the flag, not be empty.
    top_flag = (tmp_path / "runs" / "a" / "flag.txt").read_text().strip()
    assert top_flag == "flag{stdout-only-0}"


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
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()

async def test_one_exception_does_not_cancel_siblings(tmp_path, monkeypatch):
    """If one challenge's worker raises an unhandled exception (e.g., docker
    daemon down), every sibling must still complete. Before the fix,
    asyncio.gather's fail-fast default cancelled peers on the first
    exception, losing the entire batch's worth of solves."""
    async def worker(*args, **kwargs):
        if kwargs["name"] == "boom":
            raise RuntimeError("simulated docker spawn failure")
        # Populate scratch so flag_gate doesn't WARN on empty work/.
        wd = kwargs["workdir"]
        (wd / "work").mkdir(parents=True, exist_ok=True)
        (wd / "work" / "derivation.txt").write_text("solver steps\n")
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout=f"FLAG: flag{{{kwargs['name']}}}\n",
            stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=3, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
    )
    challenges = [
        Challenge(name="a", description="x"),
        Challenge(name="boom", description="x"),
        Challenge(name="b", description="x"),
    ]
    orch = Orchestrator(cfg, writer=writer)
    await orch.run(challenges)
    by_name = {r.name: r for r in writer.appended}
    assert set(by_name) == {"a", "boom", "b"}, by_name
    # Siblings solved normally.
    assert by_name["a"].status == "solved" and by_name["a"].flag == "flag{a}"
    assert by_name["b"].status == "solved" and by_name["b"].flag == "flag{b}"
    # Faulting one recorded as error with the exception info.
    assert by_name["boom"].status == "error"
    assert "simulated docker spawn failure" in (by_name["boom"].reason or "")
    # Failure markdown written for the error case.
    assert (tmp_path / "failures" / "boom.md").exists()


def test_exit_137_with_flag_is_solved_uncertain(tmp_path, monkeypatch):
    """A SIGKILL (OOM) exit must demote an otherwise-solved run.

    Build a minimal orchestrator, stub `_attempt` to return a WorkerResult
    with exit_code=137 and a flag in stdout, then run `_safe_one` and
    assert the recorded Result has status="solved_uncertain".
    """
    from hydra.orchestrator import Orchestrator, OrchestratorConfig
    from hydra.docker_worker import WorkerResult
    from hydra.models import Challenge
    from hydra.results import ResultsWriter

    runs = tmp_path / "runs"
    runs.mkdir()
    writer = ResultsWriter(
        jsonl_path=tmp_path / "results.jsonl",
        flags_path=tmp_path / "flags.json",
        results_path=tmp_path / "results.json",
    )
    cfg = OrchestratorConfig(
        parallel=1,
        timeout_s=600.0,
        model="claude-opus-4-6",
        image="hydra-worker",
        runs_dir=runs,
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    import asyncio
    orch._sem = asyncio.Semaphore(1)

    wd = runs / "Foo"
    (wd / "logs").mkdir(parents=True, exist_ok=True)
    (wd / "flag.txt").write_text("HTB{plausible_but_from_an_oom_run}\n")

    stub_wr = WorkerResult(
        name="Foo", stdout="", stderr="", exit_code=137, timed_out=False,
        duration_s=10.0,
    )

    async def _fake_attempt(self, c, subpath):
        return wd, stub_wr, None
    monkeypatch.setattr(Orchestrator, "_attempt", _fake_attempt)

    c = Challenge(name="Foo", description="x", remote="example.com:1234")
    asyncio.run(orch._safe_one(c))

    assert len(orch._results) == 1
    r = orch._results[0]
    assert r.status == "solved_uncertain", f"expected solved_uncertain, got {r.status}"
    assert "OOM" in (r.reason or "") or "137" in (r.reason or "")


async def test_gate_rejects_unclosed_flag_keeps_it_out_of_flags_json(
    tmp_path, monkeypatch
):
    """A flag whose prefix doesn't match the challenge's declared
    flag_prefix must be vetoed by the gate: status becomes 'failed' and
    no flag lands in flags.json (so --retry-failed can re-pick it).

    Note: the plan's original scenario (unclosed-brace flag.txt from the
    OT splash-array bug) is already caught upstream by
    flag_extractor.extract_flag, so it can't exercise the gate at the
    orchestrator integration level — it's covered unit-side in
    tests/unit/test_flag_gate.py::test_reject_unclosed_brace. We
    substitute prefix-mismatch here because that rule is unique to the
    gate (extract_flag doesn't know challenge.flag_prefix)."""
    async def worker_wrong_prefix(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("flag{got_this_one}\n")
        (wd / "work").mkdir(parents=True, exist_ok=True)
        (wd / "work" / "derivation.txt").write_text("solver steps\n")
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="done", stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker_wrong_prefix)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="WANLAI")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
    assert "prefix" in (r.reason or "").lower()


async def test_gate_warn_demotes_to_solved_uncertain(tmp_path, monkeypatch):
    """A flag produced with no /workspace/work scratch artifacts is
    derivation-suspect; gate WARN must demote to solved_uncertain while
    still recording the flag (user can verify)."""
    async def worker_no_scratch(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("HTB{some_body_here}\n")
        # deliberately no work/ dir
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="done", stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker_no_scratch)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="HTB")])
    [r] = writer.appended
    assert r.status == "solved_uncertain"
    assert r.flag == "HTB{some_body_here}"
    assert "no_scratch" in (r.reason or "")


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
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x"), Challenge(name="b", description="y")])
    names = [r.name for r in writer.appended]
    assert names == ["b"]


async def test_watchdog_kill_overrides_worker_result(tmp_path, monkeypatch):
    """Watchdog returning a KillReason must override the worker's own
    WorkerResult: status = failed, reason = 'watchdog: <code> (...)',
    flag = None even if flag.txt happened to hold a candidate."""
    from hydra.watchdog import KillReason, WatchdogConfig

    async def slow_worker(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("HTB{looks_good_but_loop_detected}\n")
        await asyncio.sleep(0.2)
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="", stderr="", timed_out=False, duration_s=0.2,
        )

    class InstantKillWatchdog:
        def __init__(self, *a, **kw):
            pass

        async def run(self) -> KillReason:
            return KillReason(code="bash_repeat", detail="test-triggered")

    async def no_op_stop(*args, **kwargs):
        return None

    monkeypatch.setattr("hydra.orchestrator.run_worker", slow_worker)
    monkeypatch.setattr("hydra.orchestrator.Watchdog", InstantKillWatchdog)
    monkeypatch.setattr("hydra.orchestrator.stop_container", no_op_stop)

    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=WatchdogConfig(
            cost_cap_usd=10.0, mem_kill_pct=90.0,
            max_same_bash_repeats=3, max_solver_variants=5,
            idle_work_timeout_s=180.0,
        ),
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="HTB")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
    assert "watchdog: bash_repeat" in (r.reason or "")


async def test_attempt_shares_container_name_between_worker_and_watchdog(
    tmp_path, monkeypatch
):
    """Regression for a bug where _attempt used `f"hydra-{c.name}"` while
    run_worker generated `f"hydra-<safe>-<uuid>"`. The Watchdog's
    mem_sampler and the orchestrator's stop_container both take the
    prefix-form -> neither would ever match the actual container in prod.

    After the fix, _attempt generates the canonical name ONCE and hands
    the same string to both run_worker and Watchdog.
    """
    from hydra.watchdog import KillReason, WatchdogConfig

    captured_worker: dict = {}
    captured_wd: list[str] = []
    captured_stop: list[str] = []

    async def fake_run_worker(**kwargs):
        captured_worker.update(kwargs)
        # Simulate a slow worker so the watchdog wins the race.
        await asyncio.sleep(0.5)
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="", stderr="", timed_out=False, duration_s=0.5,
        )

    class RecordingInstantKillWatchdog:
        def __init__(self, *, container_name, **kw):
            captured_wd.append(container_name)
        async def run(self) -> KillReason:
            return KillReason(code="bash_repeat", detail="test-triggered")

    async def capturing_stop(engine, name):
        captured_stop.append(name)

    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_run_worker)
    monkeypatch.setattr("hydra.orchestrator.Watchdog", RecordingInstantKillWatchdog)
    monkeypatch.setattr("hydra.orchestrator.stop_container", capturing_stop)

    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=WatchdogConfig(
            cost_cap_usd=10.0, mem_kill_pct=90.0,
            max_same_bash_repeats=3, max_solver_variants=5,
            idle_work_timeout_s=180.0,
        ),
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="Chal-1", description="x")])

    # 1. run_worker received a container_name kwarg at all.
    assert "container_name" in captured_worker
    shared = captured_worker["container_name"]
    # 2. Name has the canonical docker-safe shape.
    assert shared.startswith("hydra-Chal-1-")
    assert len(shared) > len("hydra-Chal-1-")  # has uuid suffix
    # 3. Watchdog was given the SAME name.
    assert captured_wd == [shared]
    # 4. stop_container was called with the SAME name.
    assert captured_stop == [shared]


def test_orchestrator_config_accepts_watchdog_object():
    """Collapsed config: `watchdog` is the sole knob; `None` disables."""
    from pathlib import Path as _P
    from hydra.watchdog import WatchdogConfig
    cfg_on = OrchestratorConfig(
        parallel=1, timeout_s=10, model="m",
        image="i", api_key="sk",
        runs_dir=_P("/tmp"), failures_dir=_P("/tmp"),
        prompt_volumes={},
        watchdog=WatchdogConfig(
            cost_cap_usd=5.0, mem_kill_pct=90.0,
            max_same_bash_repeats=3, max_solver_variants=5,
            idle_work_timeout_s=180.0,
        ),
    )
    assert cfg_on.watchdog is not None
    assert cfg_on.watchdog.cost_cap_usd == 5.0

    cfg_off = OrchestratorConfig(
        parallel=1, timeout_s=10, model="m",
        image="i", api_key="sk",
        runs_dir=_P("/tmp"), failures_dir=_P("/tmp"),
        prompt_volumes={},
        watchdog=None,
    )
    assert cfg_off.watchdog is None


async def test_multiple_soft_demotions_accumulate_reasons(tmp_path, monkeypatch):
    """Exit 137 + gate WARN (no_scratch) both demote to solved_uncertain.
    Reason must mention both signals so humans can verify correctly,
    not get only the first-match string."""
    async def worker_oom_no_scratch(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("HTB{body}\n")
        # no work/ dir → no_scratch WARN
        return WorkerResult(
            name=kwargs["name"], exit_code=137,
            stdout="", stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker_oom_no_scratch)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog=None,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="HTB")])
    [r] = writer.appended
    assert r.status == "solved_uncertain"
    assert "OOM" in (r.reason or "") or "137" in (r.reason or "")
    assert "no_scratch" in (r.reason or "")
