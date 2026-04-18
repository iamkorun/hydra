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
