import asyncio
import json
from pathlib import Path

import pytest

from hydra.watchdog import KillReason, Watchdog, WatchdogConfig


def _cfg(**overrides) -> WatchdogConfig:
    base = dict(
        cost_cap_usd=10.0,
        mem_kill_pct=90.0,
        max_same_bash_repeats=3,
        max_solver_variants=5,
        idle_work_timeout_s=180.0,
        poll_interval_s=0.01,
        tail_interval_s=0.01,
    )
    base.update(overrides)
    return WatchdogConfig(**base)


async def test_run_returns_when_cancelled(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(),
        mem_sampler=lambda name: 0.0,
    )
    task = asyncio.create_task(wd.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def _write_jsonl(path: Path, events: list[dict]) -> None:
    with path.open("a") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
            f.flush()
            await asyncio.sleep(0.005)


def _bash_event(command: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": f"msg_{hash(command) & 0xffff:04x}",
            "content": [{
                "type": "tool_use",
                "name": "Bash",
                "input": {"command": command},
            }],
            "usage": {"input_tokens": 1, "output_tokens": 1,
                      "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0},
        },
    }


async def test_kill_on_same_bash_repeat(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(max_same_bash_repeats=3),
        mem_sampler=lambda _: 0.0,
    )
    task = asyncio.create_task(wd.run())
    cmd = "curl http://10.0.0.1:8080/probe"
    await _write_jsonl(jsonl, [_bash_event(cmd) for _ in range(3)])
    result = await asyncio.wait_for(task, timeout=1.0)
    assert isinstance(result, KillReason)
    assert result.code == "bash_repeat"
    assert "curl http" in result.detail


async def test_distinct_bash_commands_do_not_trigger(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(max_same_bash_repeats=3),
        mem_sampler=lambda _: 0.0,
    )
    task = asyncio.create_task(wd.run())
    cmds = [f"echo {i}" for i in range(10)]
    await _write_jsonl(jsonl, [_bash_event(c) for c in cmds])
    await asyncio.sleep(0.05)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def _write_event(name: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "id": f"msg_{hash(name) & 0xffff:04x}",
            "content": [{
                "type": "tool_use",
                "name": "Write",
                "input": {"file_path": f"/workspace/work/{name}"},
            }],
            "usage": {},
        },
    }


async def test_kill_on_solver_variant_proliferation(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(max_solver_variants=5),
        mem_sampler=lambda _: 0.0,
    )
    task = asyncio.create_task(wd.run())
    await _write_jsonl(jsonl, [
        _write_event("solve1.py"), _write_event("solve2.py"),
        _write_event("solve3.py"), _write_event("solve4.py"),
        _write_event("solve5.py"),
    ])
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.code == "solver_spam"
    assert "5" in result.detail


def _assistant_usage_event(
    input_tokens: int, output_tokens: int,
    cache_creation: int = 0, cache_read: int = 0,
) -> dict:
    import uuid
    return {
        "type": "assistant",
        "message": {
            "id": f"msg_{uuid.uuid4().hex[:16]}",
            "content": [],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_input_tokens": cache_creation,
                "cache_read_input_tokens": cache_read,
            },
        },
    }


async def test_kill_on_cost_cap(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(cost_cap_usd=0.01),
        mem_sampler=lambda _: 0.0,
        model_name="claude-opus-4-7",
    )
    task = asyncio.create_task(wd.run())
    # 10_000 output tokens * $75/M = $0.75 — well over $0.01 cap.
    await _write_jsonl(jsonl, [_assistant_usage_event(0, 10_000)])
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.code == "cost_cap"


async def test_kill_on_memory_pressure(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(mem_kill_pct=90.0, poll_interval_s=0.01),
        mem_sampler=lambda _: 95.0,
    )
    task = asyncio.create_task(wd.run())
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.code == "oom_preempt"
    assert "95" in result.detail


async def test_mem_sampler_returning_none_is_ignored(tmp_path: Path):
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()
    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(mem_kill_pct=90.0, poll_interval_s=0.01),
        mem_sampler=lambda _: None,
    )
    task = asyncio.create_task(wd.run())
    await asyncio.sleep(0.1)
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_kill_on_idle_work(tmp_path: Path, monkeypatch):
    """work/ mtime unchanged past idle threshold + agent still writing
    tool_uses -> kill before further burn."""
    import os
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()

    clock = {"t": 1000.0}
    # Patch the module's thin clock wrappers — patching time.monotonic
    # globally would deadlock the asyncio event loop.
    monkeypatch.setattr("hydra.watchdog._monotonic", lambda: clock["t"])
    monkeypatch.setattr("hydra.watchdog._wall_time", lambda: clock["t"])

    wd = Watchdog(
        container_name="fake",
        jsonl_path=jsonl,
        work_dir=tmp_path / "work",
        config=_cfg(idle_work_timeout_s=60.0, poll_interval_s=0.01),
        mem_sampler=lambda _: 0.0,
    )
    task = asyncio.create_task(wd.run())

    # Seed: first tool_use at t=1000, work/ mtime fixed at t=1000.
    await _write_jsonl(jsonl, [_bash_event("echo first")])
    (tmp_path / "work" / "seed").write_text("x")
    os.utime(tmp_path / "work", (1000.0, 1000.0))

    # Jump wall+monotonic clocks forward 120s; agent still emits tools.
    clock["t"] = 1120.0
    await _write_jsonl(jsonl, [_bash_event(f"echo tick{i}") for i in range(3)])

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.code == "idle_work"


def test_docker_mem_sampler_parses_percent(monkeypatch):
    """Happy path: `docker stats` prints '12.34%\n'; sampler returns 12.34."""
    from hydra.watchdog import docker_mem_sampler

    class _Out:
        returncode = 0
        stdout = "12.34%\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Out())
    assert docker_mem_sampler()("hydra-chal-deadbeef") == 12.34


def test_docker_mem_sampler_returns_none_on_missing_container(monkeypatch):
    """Container gone → non-zero rc. Returns None (not 0.0) so the
    watchdog does not mistake 'unavailable' for 'no pressure'."""
    from hydra.watchdog import docker_mem_sampler

    class _Out:
        returncode = 1
        stdout = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Out())
    assert docker_mem_sampler()("hydra-gone") is None


def test_docker_mem_sampler_returns_none_on_timeout(monkeypatch):
    """docker daemon hang → subprocess timeout → None."""
    import subprocess as _sp
    from hydra.watchdog import docker_mem_sampler

    def _boom(*a, **kw):
        raise _sp.TimeoutExpired(cmd="docker", timeout=5)

    monkeypatch.setattr("subprocess.run", _boom)
    assert docker_mem_sampler()("hydra-slow") is None


def test_docker_mem_sampler_returns_none_on_unparseable(monkeypatch):
    """Some stats output forms (e.g. '--') aren't floats. Return None."""
    from hydra.watchdog import docker_mem_sampler

    class _Out:
        returncode = 0
        stdout = "--\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Out())
    assert docker_mem_sampler()("hydra-new") is None
