import asyncio
from pathlib import Path

import pytest

from hydra.watchdog import Watchdog, WatchdogConfig


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
