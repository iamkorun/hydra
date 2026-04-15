"""Token + cost accounting for Claude Code `stream-json` transcripts.

The Claude Code CLI emits a newline-delimited stream of JSON events while
it works. The terminal `result` event carries an authoritative
`total_cost_usd` and aggregated `usage` (input/output + cache tokens); for
runs that got cancelled or killed before completion, we reconstruct the
same shape from the per-message usages emitted on `assistant` events.

This module is pure — no Docker, no orchestration. Orchestrator calls
`parse_usage_dir(runs_dir / challenge_name)` after the worker returns.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


_LOG_GLOB = "logs/claude.stdout.jsonl"


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_input_tokens=(
                self.cache_read_input_tokens + other.cache_read_input_tokens
            ),
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            cost_usd=self.cost_usd + other.cost_usd,
        )


def _usage_from_dict(u: dict) -> Usage:
    return Usage(
        input_tokens=int(u.get("input_tokens") or 0),
        output_tokens=int(u.get("output_tokens") or 0),
        cache_read_input_tokens=int(u.get("cache_read_input_tokens") or 0),
        cache_creation_input_tokens=int(u.get("cache_creation_input_tokens") or 0),
    )


def _usage_from_model_usage(model_usage: dict) -> Usage | None:
    """Sum per-model usage from `result.modelUsage`.

    Claude Code's stream-json reports *two* usage shapes on the terminal
    `result` event. `usage` (snake_case) is the main-session only; when
    subagents (Task tool) are dispatched their tokens land in
    `modelUsage.<model-id>` (camelCase) instead. Using top-level `usage`
    under-reports totals by ~5x for multi-agent runs.

    Returns None when `modelUsage` is missing/malformed so callers can
    fall back to top-level `usage`. Cost is not read here; pull it from
    `total_cost_usd` which covers both single- and multi-agent runs.
    """
    if not isinstance(model_usage, dict) or not model_usage:
        return None
    total = Usage()
    for per_model in model_usage.values():
        if not isinstance(per_model, dict):
            return None
        total = total + Usage(
            input_tokens=int(per_model.get("inputTokens") or 0),
            output_tokens=int(per_model.get("outputTokens") or 0),
            cache_read_input_tokens=int(per_model.get("cacheReadInputTokens") or 0),
            cache_creation_input_tokens=int(
                per_model.get("cacheCreationInputTokens") or 0
            ),
        )
    return total


def parse_usage(jsonl_path: Path) -> Usage:
    """Extract per-run token + cost totals from one stream-json transcript.

    Prefers the terminal `result` event when present (authoritative). For
    truncated transcripts (timeout/cancel/crash), falls back to summing
    per-message usages deduped by `message.id` so streaming deltas don't
    double-count. Missing cost in fallback mode is expected — Claude CLI
    only emits `total_cost_usd` in `result`.
    """
    if not jsonl_path.is_file():
        return Usage()

    result_usage: Usage | None = None
    per_msg: dict[str, Usage] = {}

    try:
        content = jsonl_path.read_text()
    except OSError:
        return Usage()

    for line in content.splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = e.get("type")
        if etype == "result":
            cost = float(e.get("total_cost_usd") or 0.0)
            mu = _usage_from_model_usage(e.get("modelUsage") or {})
            if mu is not None:
                result_usage = Usage(
                    input_tokens=mu.input_tokens,
                    output_tokens=mu.output_tokens,
                    cache_read_input_tokens=mu.cache_read_input_tokens,
                    cache_creation_input_tokens=mu.cache_creation_input_tokens,
                    cost_usd=cost,
                )
            else:
                u = e.get("usage") or {}
                result_usage = Usage(
                    input_tokens=int(u.get("input_tokens") or 0),
                    output_tokens=int(u.get("output_tokens") or 0),
                    cache_read_input_tokens=int(u.get("cache_read_input_tokens") or 0),
                    cache_creation_input_tokens=int(
                        u.get("cache_creation_input_tokens") or 0
                    ),
                    cost_usd=cost,
                )
        elif etype == "assistant":
            msg = e.get("message") or {}
            mid = msg.get("id")
            u = msg.get("usage")
            if mid and u:
                # Latest usage for this message id wins (streaming deltas
                # overwrite instead of accumulating).
                per_msg[mid] = _usage_from_dict(u)

    if result_usage is not None:
        return result_usage
    return sum_usages(list(per_msg.values()))


def parse_usage_dir(work_dir: Path) -> Usage:
    """Sum `parse_usage` across every transcript under `work_dir`.

    Covers both layouts: non-pass@k (`runs/<name>/logs/claude.stdout.jsonl`)
    and pass@k (`runs/<name>/a{k}/logs/claude.stdout.jsonl`). For pass@k,
    summing is the right accounting — you pay for losers until cancel.
    """
    if not work_dir.is_dir():
        return Usage()
    total = Usage()
    for p in work_dir.rglob(_LOG_GLOB):
        total = total + parse_usage(p)
    return total


def sum_usages(usages: list[Usage]) -> Usage:
    total = Usage()
    for u in usages:
        total = total + u
    return total
