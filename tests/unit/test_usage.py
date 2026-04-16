"""Tests for hydra.usage — token/cost accounting from Claude Code stream-json."""
import json
from pathlib import Path

from hydra.usage import Usage, parse_usage, parse_usage_dir, sum_usages


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")


def test_usage_add_is_componentwise():
    a = Usage(input_tokens=10, output_tokens=5, cache_read_input_tokens=100,
              cache_creation_input_tokens=200, cost_usd=0.01)
    b = Usage(input_tokens=1, output_tokens=2, cache_read_input_tokens=3,
              cache_creation_input_tokens=4, cost_usd=0.001)
    c = a + b
    assert c == Usage(11, 7, 103, 204, 0.011)


def test_parse_usage_prefers_result_event(tmp_path: Path):
    """When a terminal `result` event exists, its usage + total_cost_usd
    are authoritative — ignore per-message events."""
    log = tmp_path / "claude.stdout.jsonl"
    _write_jsonl(log, [
        {"type": "assistant", "message": {"id": "msg_1",
            "usage": {"input_tokens": 999, "output_tokens": 999,
                      "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 0}}},
        {"type": "result", "subtype": "success", "total_cost_usd": 0.42,
         "usage": {"input_tokens": 10, "output_tokens": 69,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 50818}},
    ])
    u = parse_usage(log)
    assert u.cost_usd == 0.42
    assert u.input_tokens == 10
    assert u.output_tokens == 69
    assert u.cache_creation_input_tokens == 50818


def test_parse_usage_prefers_model_usage_when_present(tmp_path: Path):
    """When `result` carries `modelUsage`, it is the true run-level total
    including subagent (Task-tool) calls; top-level `usage` is the main
    session only and under-reports by up to 5x when specialists are
    dispatched. Cost still comes from `total_cost_usd`."""
    log = tmp_path / "claude.stdout.jsonl"
    _write_jsonl(log, [
        {"type": "result", "subtype": "success", "total_cost_usd": 1.087,
         "usage": {"input_tokens": 10, "output_tokens": 1888,
                   "cache_read_input_tokens": 248757,
                   "cache_creation_input_tokens": 7657},
         "modelUsage": {
             "claude-opus-4-7": {
                 "inputTokens": 42,
                 "outputTokens": 9921,
                 "cacheReadInputTokens": 1130064,
                 "cacheCreationInputTokens": 43791,
                 "costUSD": 1.087,
             }
         }},
    ])
    u = parse_usage(log)
    assert u.cost_usd == 1.087
    assert u.input_tokens == 42
    assert u.output_tokens == 9921
    assert u.cache_read_input_tokens == 1130064
    assert u.cache_creation_input_tokens == 43791


def test_parse_usage_sums_across_models(tmp_path: Path):
    """Mixed-model runs (e.g. opus triage + haiku worker) report per-model
    usage. Sum them for the run-level total."""
    log = tmp_path / "claude.stdout.jsonl"
    _write_jsonl(log, [
        {"type": "result", "subtype": "success", "total_cost_usd": 1.5,
         "usage": {"input_tokens": 0, "output_tokens": 0,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0},
         "modelUsage": {
             "claude-opus-4-7": {
                 "inputTokens": 100, "outputTokens": 200,
                 "cacheReadInputTokens": 1000,
                 "cacheCreationInputTokens": 50,
             },
             "claude-haiku-4-5": {
                 "inputTokens": 10, "outputTokens": 20,
                 "cacheReadInputTokens": 500,
                 "cacheCreationInputTokens": 5,
             },
         }},
    ])
    u = parse_usage(log)
    assert u.input_tokens == 110
    assert u.output_tokens == 220
    assert u.cache_read_input_tokens == 1500
    assert u.cache_creation_input_tokens == 55
    assert u.cost_usd == 1.5


def test_parse_usage_tolerates_malformed_model_usage(tmp_path: Path):
    """Schema drift: if modelUsage isn't a dict-of-dicts, fall back to
    top-level `usage` rather than crashing."""
    log = tmp_path / "claude.stdout.jsonl"
    _write_jsonl(log, [
        {"type": "result", "subtype": "success", "total_cost_usd": 0.1,
         "usage": {"input_tokens": 5, "output_tokens": 6,
                   "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0},
         "modelUsage": "not-a-dict"},
    ])
    u = parse_usage(log)
    assert u.input_tokens == 5
    assert u.output_tokens == 6
    assert u.cost_usd == 0.1


def test_parse_usage_falls_back_to_per_message_sum(tmp_path: Path):
    """When no `result` event exists (cancelled/killed run), sum per-message
    usages, deduped by message id so streaming repeats don't double-count."""
    log = tmp_path / "claude.stdout.jsonl"
    _write_jsonl(log, [
        {"type": "assistant", "message": {"id": "msg_1",
            "usage": {"input_tokens": 10, "output_tokens": 1,
                      "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 50000}}},
        # Same msg_1 streamed again with richer content — must not double-count.
        {"type": "assistant", "message": {"id": "msg_1",
            "usage": {"input_tokens": 10, "output_tokens": 5,
                      "cache_read_input_tokens": 0,
                      "cache_creation_input_tokens": 50000}}},
        {"type": "assistant", "message": {"id": "msg_2",
            "usage": {"input_tokens": 20, "output_tokens": 3,
                      "cache_read_input_tokens": 50000,
                      "cache_creation_input_tokens": 0}}},
    ])
    u = parse_usage(log)
    assert u.input_tokens == 30   # msg_1 (10, latest) + msg_2 (20)
    assert u.output_tokens == 8   # 5 + 3
    assert u.cache_read_input_tokens == 50000
    assert u.cache_creation_input_tokens == 50000
    # No `result` event means no authoritative cost — stays 0.
    assert u.cost_usd == 0.0


def test_parse_usage_missing_file_returns_zero(tmp_path: Path):
    u = parse_usage(tmp_path / "does-not-exist.jsonl")
    assert u == Usage()


def test_parse_usage_tolerates_malformed_lines(tmp_path: Path):
    """Partial writes or schema drift must not crash the parser — agents
    die mid-stream all the time and we still want costs for what ran."""
    log = tmp_path / "claude.stdout.jsonl"
    log.write_text(
        "not-json-at-all\n"
        + json.dumps({"type": "result", "total_cost_usd": 0.05,
                      "usage": {"input_tokens": 1, "output_tokens": 2,
                                "cache_read_input_tokens": 0,
                                "cache_creation_input_tokens": 0}}) + "\n"
        + "\n"  # blank line
    )
    u = parse_usage(log)
    assert u.cost_usd == 0.05
    assert u.input_tokens == 1


def test_parse_usage_dir_sums_all_attempts(tmp_path: Path):
    """pass@k stores each attempt under runs/<name>/a{k}/logs/. The
    challenge-level cost is the sum across all K attempts — we pay for
    losers too until they're cancelled, so accountability requires summing."""
    for i, cost in enumerate([0.10, 0.20, 0.30], start=1):
        _write_jsonl(
            tmp_path / f"a{i}" / "logs" / "claude.stdout.jsonl",
            [{"type": "result", "total_cost_usd": cost,
              "usage": {"input_tokens": 10, "output_tokens": 5,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0}}],
        )
    u = parse_usage_dir(tmp_path)
    assert u.cost_usd == 0.60
    assert u.input_tokens == 30
    assert u.output_tokens == 15


def test_parse_usage_dir_handles_flat_non_passk_layout(tmp_path: Path):
    """Non-pass@k layout: runs/<name>/logs/claude.stdout.jsonl directly."""
    _write_jsonl(
        tmp_path / "logs" / "claude.stdout.jsonl",
        [{"type": "result", "total_cost_usd": 0.08,
          "usage": {"input_tokens": 10, "output_tokens": 69,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 200}}],
    )
    u = parse_usage_dir(tmp_path)
    assert u.cost_usd == 0.08
    assert u.cache_read_input_tokens == 100


def test_parse_usage_dir_missing_returns_zero(tmp_path: Path):
    u = parse_usage_dir(tmp_path / "does-not-exist")
    assert u == Usage()


def test_sum_usages_empty_is_zero():
    assert sum_usages([]) == Usage()


def test_sum_usages_aggregates():
    total = sum_usages([
        Usage(input_tokens=1, cost_usd=0.1),
        Usage(output_tokens=2, cost_usd=0.2),
        Usage(cache_read_input_tokens=3),
    ])
    assert total == Usage(1, 2, 3, 0, 0.30000000000000004) or total.input_tokens == 1
    # Guard against float jitter explicitly:
    assert total.input_tokens == 1
    assert total.output_tokens == 2
    assert total.cache_read_input_tokens == 3
    assert abs(total.cost_usd - 0.3) < 1e-9
