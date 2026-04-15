"""Live progress rendering for long-running batch runs.

Problem: a single challenge can run 30+ minutes. Without feedback users
can't distinguish "agent is working hard" from "something hung". This
module tails each running challenge's transcript and redraws a compact
status block every `interval_s` seconds.

Design:
- TTY-aware: in non-interactive output (pipes, CI, log capture) stays
  silent so caller logs don't fill with ANSI noise. Completion lines
  still print normally.
- Redraws in place using ANSI cursor-up + clear-below; no scroll churn.
- Completion lines go through `print_permanent()` which atomically
  clears the live region, emits the line above it, and lets the next
  tick redraw. Without this the heartbeat would overwrite ✓/✗ results.
- Pure data sources: reuses `parse_usage_dir` for cost and counts
  `tool_use` events directly from the stream-json transcript; no IPC
  with the worker.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from hydra.usage import parse_usage_dir

_CURSOR_UP = "\033[{n}A"
_CLEAR_BELOW = "\033[J"
_DEFAULT_INTERVAL = 15.0
_TRANSCRIPT_GLOB = "logs/claude.stdout.jsonl"


def fmt_duration(seconds: float) -> str:
    """Compact human duration: 42s / 3m07s / 1h15m."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def count_tool_uses(work_dir: Path) -> int:
    """Count `tool_use` events across every transcript under work_dir.

    Tolerates partial writes — a streaming jsonl may have a half-written
    tail. We never want the progress display to crash on bad lines.
    """
    if not work_dir.is_dir():
        return 0
    total = 0
    for p in work_dir.rglob(_TRANSCRIPT_GLOB):
        try:
            text = p.read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") != "assistant":
                continue
            for c in (e.get("message") or {}).get("content") or []:
                if isinstance(c, dict) and c.get("type") == "tool_use":
                    total += 1
    return total


def build_status_line(
    name: str, elapsed_s: float, tools: int, cost_usd: float
) -> str:
    return (
        f"  \u23f3 {name:<24s} {fmt_duration(elapsed_s):>7s}  "
        f"{tools:>3d} tools  ${cost_usd:0.3f}"
    )


@dataclass
class _RunState:
    start: float
    workdir: Path


class Heartbeat:
    """Async context manager that draws a live status block.

    Usage:
        async with Heartbeat() as hb:
            hb.track("foo", workdir)
            ...
            hb.untrack("foo")
            await hb.print_permanent("foo done")
    """

    def __init__(
        self,
        *,
        interval_s: float = _DEFAULT_INTERVAL,
        stream: TextIO | None = None,
    ) -> None:
        self.interval_s = interval_s
        self._stream: TextIO = stream if stream is not None else sys.stdout
        self._tty = hasattr(self._stream, "isatty") and self._stream.isatty()
        self._running: dict[str, _RunState] = {}
        self._last_lines = 0
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    @property
    def active(self) -> bool:
        return self._tty

    async def __aenter__(self) -> Heartbeat:
        if self._tty:
            self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        async with self._lock:
            self._clear_unlocked()

    def track(self, name: str, workdir: Path) -> None:
        self._running[name] = _RunState(start=time.monotonic(), workdir=workdir)

    def untrack(self, name: str) -> None:
        self._running.pop(name, None)

    async def print_permanent(self, line: str) -> None:
        """Emit `line` above the live region without colliding with it.

        Safe to call from any task; holds the draw lock so we never
        interleave bytes mid-escape-sequence.
        """
        async with self._lock:
            self._clear_unlocked()
            self._stream.write(line + "\n")
            self._stream.flush()

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.interval_s)
                async with self._lock:
                    self._draw_unlocked()
        except asyncio.CancelledError:
            raise

    def _draw_unlocked(self) -> None:
        self._clear_unlocked()
        if not self._running:
            return
        now = time.monotonic()
        lines = []
        for name, rs in list(self._running.items()):
            elapsed = now - rs.start
            tools = count_tool_uses(rs.workdir)
            cost = parse_usage_dir(rs.workdir).cost_usd
            lines.append(build_status_line(name, elapsed, tools, cost))
        self._stream.write("\n".join(lines) + "\n")
        self._stream.flush()
        self._last_lines = len(lines)

    def _clear_unlocked(self) -> None:
        if self._last_lines and self._tty:
            self._stream.write(_CURSOR_UP.format(n=self._last_lines))
            self._stream.write(_CLEAR_BELOW)
            self._stream.flush()
        self._last_lines = 0
