"""Tests for hydra.heartbeat — live progress rendering."""
import asyncio
import io
import json
from pathlib import Path

import pytest

from hydra.heartbeat import (
    Heartbeat,
    build_status_line,
    count_tool_uses,
    fmt_duration,
)


class _PipeStream(io.StringIO):
    """A non-TTY stream for testing TTY-gated behavior."""
    def isatty(self) -> bool:
        return False


class _TTYStream(io.StringIO):
    """A stream that reports as a TTY so we can exercise the draw path."""
    def isatty(self) -> bool:
        return True


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


# --- pure helpers -----------------------------------------------------------

def test_fmt_duration_sub_minute():
    assert fmt_duration(0) == "0s"
    assert fmt_duration(42.4) == "42s"
    assert fmt_duration(59.9) == "60s"


def test_fmt_duration_minutes():
    assert fmt_duration(60) == "1m00s"
    assert fmt_duration(187) == "3m07s"


def test_fmt_duration_hours():
    assert fmt_duration(3600) == "1h00m"
    assert fmt_duration(4515) == "1h15m"


def test_build_status_line_contains_key_fields():
    s = build_status_line("Wannacry", 130.0, 7, 0.423)
    assert "Wannacry" in s
    assert "2m10s" in s
    assert "7 tools" in s
    assert "$0.423" in s


def test_count_tool_uses_sums_across_attempts(tmp_path: Path):
    """pass@k layout: runs/<name>/a1/logs/..., runs/<name>/a2/logs/..."""
    _write_jsonl(tmp_path / "a1" / "logs" / "claude.stdout.jsonl", [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash"},
            {"type": "tool_use", "name": "Read"},
        ]}},
    ])
    _write_jsonl(tmp_path / "a2" / "logs" / "claude.stdout.jsonl", [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Glob"},
            {"type": "text", "text": "hello"},
        ]}},
    ])
    assert count_tool_uses(tmp_path) == 3


def test_count_tool_uses_tolerates_partial_writes(tmp_path: Path):
    """Streaming transcript may have a truncated tail. Progress display
    must never crash on it."""
    log = tmp_path / "logs" / "claude.stdout.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash"},
        ]}}) + "\n"
        + '{"type": "assistant", "message": {"content": [{"type":"tool_us'  # truncated
    )
    assert count_tool_uses(tmp_path) == 1


def test_count_tool_uses_missing_dir():
    assert count_tool_uses(Path("/definitely/not/a/dir")) == 0


# --- Heartbeat behavior -----------------------------------------------------

@pytest.mark.asyncio
async def test_non_tty_writes_nothing(tmp_path: Path):
    """Piped output must stay silent (no ANSI codes in logs/CI)."""
    out = _PipeStream()
    async with Heartbeat(interval_s=0.01, stream=out) as hb:
        hb.track("a", tmp_path)
        await asyncio.sleep(0.05)
        hb.untrack("a")
    assert out.getvalue() == ""
    assert hb.active is False


@pytest.mark.asyncio
async def test_print_permanent_always_writes_even_when_not_tty(tmp_path: Path):
    """Completion lines must appear regardless of TTY state — they're
    the primary signal for pipelines grepping stdout."""
    out = _PipeStream()
    async with Heartbeat(interval_s=60.0, stream=out) as hb:
        await hb.print_permanent("\u2713 done")
    assert "\u2713 done" in out.getvalue()


@pytest.mark.asyncio
async def test_tty_draws_running_challenges(tmp_path: Path):
    """With a TTY stream, the live loop renders a line per tracked run."""
    _write_jsonl(tmp_path / "logs" / "claude.stdout.jsonl", [
        {"type": "result", "total_cost_usd": 0.12,
         "usage": {"input_tokens": 1, "output_tokens": 1,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0}},
    ])
    out = _TTYStream()
    async with Heartbeat(interval_s=0.02, stream=out) as hb:
        hb.track("demo", tmp_path)
        await asyncio.sleep(0.08)  # give ≥1 tick time to fire
        hb.untrack("demo")
    rendered = out.getvalue()
    assert "demo" in rendered
    assert "$0.120" in rendered


@pytest.mark.asyncio
async def test_print_permanent_clears_live_block_first(tmp_path: Path):
    """Between ticks, print_permanent must emit ANSI clear codes before
    the line so the prior heartbeat block doesn't get duplicated."""
    _write_jsonl(tmp_path / "logs" / "claude.stdout.jsonl", [
        {"type": "result", "total_cost_usd": 0.05,
         "usage": {"input_tokens": 1, "output_tokens": 1,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0}},
    ])
    out = _TTYStream()
    async with Heartbeat(interval_s=0.02, stream=out) as hb:
        hb.track("x", tmp_path)
        await asyncio.sleep(0.08)
        await hb.print_permanent("\u2713 x done")
        hb.untrack("x")
    rendered = out.getvalue()
    # The permanent line lands after a cursor-up escape.
    assert "\u2713 x done" in rendered
    assert "\033[" in rendered  # some ANSI was written


@pytest.mark.asyncio
async def test_exit_clears_final_block(tmp_path: Path):
    """On context exit the live region must be wiped so subsequent
    prints (e.g., the batch summary) don't sit under stale heartbeat
    characters."""
    _write_jsonl(tmp_path / "logs" / "claude.stdout.jsonl", [
        {"type": "result", "total_cost_usd": 0.01,
         "usage": {"input_tokens": 1, "output_tokens": 1,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0}},
    ])
    out = _TTYStream()
    hb = Heartbeat(interval_s=0.02, stream=out)
    async with hb:
        hb.track("x", tmp_path)
        await asyncio.sleep(0.08)
        hb.untrack("x")
    # After exit, the last thing written should include the clear-below
    # escape so downstream prints start on a clean line.
    assert "\033[J" in out.getvalue()
