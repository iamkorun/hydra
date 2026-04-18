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
import json
import time
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
        """Poll-tail the jsonl file and dispatch parsed events to
        event-based evaluators. Returns on the first kill signal."""
        pos = 0
        while True:
            try:
                data = self.jsonl_path.read_text()
            except (FileNotFoundError, OSError):
                data = ""
            if len(data) > pos:
                fresh = data[pos:]
                pos = len(data)
                for line in fresh.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    reason = self._on_event(event)
                    if reason:
                        return reason
            await asyncio.sleep(self.cfg.tail_interval_s)

    def _on_event(self, event: dict) -> KillReason | None:
        if event.get("type") != "assistant":
            return None
        msg = event.get("message") or {}
        for block in msg.get("content") or []:
            if block.get("type") != "tool_use":
                continue
            now = time.monotonic()
            if self._state.first_tool_use_ts == 0.0:
                self._state.first_tool_use_ts = now
            self._state.last_tool_use_ts = now
            if block.get("name") == "Bash":
                cmd = (block.get("input") or {}).get("command", "")
                reason = self._check_bash_repeat(cmd)
                if reason:
                    return reason
        return None

    def _check_bash_repeat(self, command: str) -> KillReason | None:
        prefix = command[:50]
        self._state.bash_counts[prefix] += 1
        if self._state.bash_counts[prefix] >= self.cfg.max_same_bash_repeats:
            return KillReason(
                code="bash_repeat",
                detail=f"same Bash {self.cfg.max_same_bash_repeats}x: {prefix!r}",
            )
        return None

    async def _poll_loop(self) -> KillReason:
        while True:
            await asyncio.sleep(self.cfg.poll_interval_s)
