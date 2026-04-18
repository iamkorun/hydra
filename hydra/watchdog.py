"""Per-worker deterministic supervisor.

Runs alongside `docker_worker.run_worker` as an asyncio task. Tails
`logs/claude.stdout.jsonl` for agent-behavior signals and polls
`docker stats` for memory pressure. When any rule fires, `run()`
returns a `KillReason`; the orchestrator then stops the container
and records the result as `failed` with
`reason='watchdog: <code> (<detail>)'`.

No Anthropic API calls. No LLM. All signals are counters / regex /
arithmetic on the stream-json events the agent already writes.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class KillReason:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"watchdog: {self.code} ({self.detail})"


@dataclass(frozen=True)
class WatchdogConfig:
    cost_cap_usd: float
    mem_kill_pct: float
    max_same_bash_repeats: int
    max_solver_variants: int
    idle_work_timeout_s: float
    poll_interval_s: float = 30.0
    tail_interval_s: float = 2.0


@dataclass
class _TailState:
    bash_counts: Counter = field(default_factory=Counter)
    last_tool_use_ts: float = 0.0
    first_tool_use_ts: float = 0.0
    solver_variants: set[str] = field(default_factory=set)
    cost_usd: float = 0.0


class Watchdog:
    def __init__(
        self,
        *,
        container_name: str,
        jsonl_path: Path,
        work_dir: Path,
        config: WatchdogConfig,
        mem_sampler: Callable[[str], float | None],
        model_name: str = "claude-opus-4-7",
    ):
        self.container_name = container_name
        self.jsonl_path = jsonl_path
        self.work_dir = work_dir
        self.cfg = config
        self.mem_sampler = mem_sampler
        self.model_name = model_name
        self._state = _TailState()
        self._msg_cost: dict[str, float] = {}

    async def run(self) -> KillReason:
        """Monitor until a rule fires. Returns the triggering reason.

        Cancellation is the normal shutdown path — if the worker exits
        first, the orchestrator cancels this task.
        """
        tail = asyncio.create_task(self._tail_loop())
        poll = asyncio.create_task(self._poll_loop())
        try:
            done, pending = await asyncio.wait(
                [tail, poll], return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            return next(iter(done)).result()
        except asyncio.CancelledError:
            for t in (tail, poll):
                t.cancel()
            await asyncio.gather(tail, poll, return_exceptions=True)
            raise

    async def _tail_loop(self) -> KillReason:
        while True:
            await asyncio.sleep(self.cfg.tail_interval_s)

    async def _poll_loop(self) -> KillReason:
        while True:
            await asyncio.sleep(self.cfg.poll_interval_s)
