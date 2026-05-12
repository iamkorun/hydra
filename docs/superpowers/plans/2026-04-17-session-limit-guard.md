# Session-Limit Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the orchestrator from bleeding into Claude Max overage usage when the 5-hour subscription window is near its quota — pre-dispatch check via `ccusage` (proactive) and transcript scan for limit errors (reactive). Unsolved challenges are converted to a new `skipped_limit` status with reset-time reason, and failure-summary reports them under a dedicated section.

**Architecture:** Three layers. (1) **`hydra/session_guard.py`** — pure functions that shell out to `ccusage blocks --active --token-limit max --json`, parse `tokenLimitStatus.{percentUsed,status,limit,projectedUsage}` (+ `endTime`), and scan a transcript for limit-error phrases. Missing/failing `ccusage` returns `None` → no-op. (2) **`hydra/orchestrator.py`** — before each slot spends tokens, call the guard; after each worker returns, scan transcript. Trip a single `_limit_tripped` flag on the orchestrator instance; subsequent `_safe_one` bails with a `skipped_limit` Result instead of calling the worker. (3) **`hydra/models.py` + `hydra/failures.py` + `hydra/cli.py`** — extend `Status` literal, segregate skipped rows in `SUMMARY.md`, add `--session-pct-cap` / `--no-session-check` CLI flags.

**Tech Stack:** Python 3.12, pytest (async), `ccusage` (Bun-installed at `~/.bun/bin/ccusage`), subprocess + json.

---

## File Structure

```
hydra/
├── hydra/
│   ├── session_guard.py                              # NEW (Tasks 1 + 2)
│   ├── models.py                                     # Task 3
│   ├── orchestrator.py                               # Task 4
│   ├── failures.py                                   # Task 5
│   └── cli.py                                        # Task 6
└── tests/unit/
    ├── test_session_guard.py                         # NEW (Tasks 1 + 2)
    ├── test_orchestrator.py                          # Task 4
    └── test_failures.py                              # Task 5
```

Six tasks, one commit each. All within `pytest tests/unit/` scope; no Docker image rebuild needed.

---

## Task 1: session_guard — ccusage-backed proactive check

Create the module with two pure helpers: `fetch_active_block()` (runs ccusage, returns parsed dict or None) and `should_abort(block, pct_cap)` (returns `(bool, reason)`). Neither is async.

**Files:**
- Create: `hydra/session_guard.py`
- Test: `tests/unit/test_session_guard.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_session_guard.py
import json
import subprocess
from hydra import session_guard


def _mk_block(**overrides):
    base = {
        "id": "2026-04-17T16:00:00.000Z",
        "isActive": True,
        "isGap": False,
        "endTime": "2026-04-17T21:00:00.000Z",
        "totalTokens": 50_000_000,
        "costUSD": 12.34,
        "tokenLimitStatus": {
            "limit": 66_578_396,
            "projectedUsage": 60_000_000,
            "percentUsed": 90.1,
            "status": "warning",
        },
    }
    base.update(overrides)
    return base


def test_fetch_active_block_returns_block(monkeypatch):
    stdout = json.dumps({"blocks": [_mk_block()]}).encode()
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=b"",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    b = session_guard.fetch_active_block()
    assert b is not None
    assert b["tokenLimitStatus"]["percentUsed"] == 90.1


def test_fetch_active_block_returns_none_when_ccusage_missing(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("ccusage")
    monkeypatch.setattr(subprocess, "run", boom)
    assert session_guard.fetch_active_block() is None


def test_fetch_active_block_returns_none_when_ccusage_nonzero(monkeypatch):
    fake = subprocess.CompletedProcess(
        args=[], returncode=1, stdout=b"", stderr=b"ccusage: oops",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    assert session_guard.fetch_active_block() is None


def test_fetch_active_block_returns_none_when_no_active_block(monkeypatch):
    stdout = json.dumps({"blocks": []}).encode()
    fake = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=b"",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
    assert session_guard.fetch_active_block() is None


def test_should_abort_under_threshold_returns_false():
    b = _mk_block(tokenLimitStatus={
        "limit": 100, "projectedUsage": 80, "percentUsed": 80.0, "status": "warning"
    })
    abort, reason = session_guard.should_abort(b, pct_cap=95.0)
    assert abort is False
    assert reason == ""


def test_should_abort_over_threshold_returns_true_with_reason():
    b = _mk_block(tokenLimitStatus={
        "limit": 100, "projectedUsage": 96, "percentUsed": 96.0, "status": "warning"
    })
    abort, reason = session_guard.should_abort(b, pct_cap=95.0)
    assert abort is True
    assert "96.0" in reason
    assert "21:00" in reason  # reset time from endTime


def test_should_abort_when_ccusage_status_exceeded():
    b = _mk_block(tokenLimitStatus={
        "limit": 100, "projectedUsage": 110, "percentUsed": 110.0, "status": "exceeded"
    })
    abort, reason = session_guard.should_abort(b, pct_cap=95.0)
    assert abort is True
    assert "exceeded" in reason.lower()


def test_should_abort_when_token_limit_status_missing():
    """Plan lookup failed — don't abort, let work continue (fail-open)."""
    b = _mk_block()
    del b["tokenLimitStatus"]
    abort, reason = session_guard.should_abort(b, pct_cap=95.0)
    assert abort is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <repo-root> && pytest tests/unit/test_session_guard.py -v`
Expected: `ModuleNotFoundError: No module named 'hydra.session_guard'`

- [ ] **Step 3: Implement `hydra/session_guard.py`**

```python
"""Proactive + reactive guards against Claude Max session-limit overage.

The orchestrator fires many Docker workers in parallel, each consuming the
host user's 5-hour subscription quota. When the quota is near its cap, we
want to stop dispatching (proactive) or stop immediately on limit errors
(reactive) rather than silently spilling into pay-as-you-go overage.

`fetch_active_block` shells out to `ccusage` (https://github.com/ryoppippi/ccusage)
and returns the single active 5h block dict (or None when ccusage is
unavailable / no active block). `should_abort` applies a percent threshold
against the plan's `tokenLimitStatus.percentUsed` — fail-open on missing
data so a broken ccusage never aborts a batch unnecessarily.

`transcript_has_limit_error` scans the tail of a stream-json transcript
for phrases Claude Code emits when quota is hit. It's the reactive
fallback for the window between proactive ticks.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

_CCUSAGE_CMD = [
    "ccusage", "blocks", "--active", "--token-limit", "max", "--json",
]

# Phrases Claude Code emits when the 5h subscription window is exhausted.
# Conservative list — string-matching the tail is cheap; the cost of a
# false positive (abort a batch) is higher than a false negative (one
# more worker bleeds into overage), so keep patterns specific.
_LIMIT_PHRASES = (
    "5-hour limit reached",
    "usage limit reached",
    "Claude usage limit reached",
    "rate_limit_error",
    "Your limit will reset at",
)


def fetch_active_block(timeout_s: float = 5.0) -> dict | None:
    """Return the single active ccusage block dict, or None on any failure.

    Fail-open: ccusage missing, nonzero exit, malformed JSON, or no active
    block all return None so a broken guard never aborts the batch.
    """
    try:
        proc = subprocess.run(
            _CCUSAGE_CMD, capture_output=True, timeout=timeout_s, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    blocks = data.get("blocks") or []
    if not blocks:
        return None
    for b in blocks:
        if b.get("isActive"):
            return b
    return None


def should_abort(block: dict, *, pct_cap: float) -> tuple[bool, str]:
    """Return (abort?, reason). Fail-open when tokenLimitStatus missing."""
    status = block.get("tokenLimitStatus")
    if not isinstance(status, dict):
        return False, ""
    pct = status.get("percentUsed")
    tls_status = (status.get("status") or "").lower()
    reset = _fmt_reset(block.get("endTime"))
    if tls_status == "exceeded":
        return True, f"Claude session quota exceeded (resets {reset})"
    if isinstance(pct, (int, float)) and pct >= pct_cap:
        limit = status.get("limit")
        projected = status.get("projectedUsage")
        return True, (
            f"Claude session at {pct:.1f}% of plan "
            f"(projected {projected}/{limit} tokens, resets {reset})"
        )
    return False, ""


def transcript_has_limit_error(jsonl_path: Path, *, tail_bytes: int = 65536) -> bool:
    """Scan the tail of a stream-json transcript for limit-error phrases."""
    if not jsonl_path.is_file():
        return False
    try:
        size = jsonl_path.stat().st_size
        with jsonl_path.open("rb") as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
            data = f.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    return any(p in data for p in _LIMIT_PHRASES)


def _fmt_reset(end_iso: str | None) -> str:
    if not end_iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M UTC")
    except (TypeError, ValueError):
        return end_iso
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd <repo-root> && pytest tests/unit/test_session_guard.py -v`
Expected: all 8 tests pass (7 existing + the "exceeded" case).

- [ ] **Step 5: Commit**

```bash
cd <repo-root>
git add hydra/session_guard.py tests/unit/test_session_guard.py
git commit -m "feat(session-guard): ccusage-backed proactive quota check"
```

---

## Task 2: session_guard — transcript limit-error scan

Already defined `transcript_has_limit_error` in Task 1's source. Add its tests now (kept separate to land a focused commit that exercises the reactive path with a real file fixture).

**Files:**
- Test: `tests/unit/test_session_guard.py` (append)

- [ ] **Step 1: Add the failing tests**

```python
# Append to tests/unit/test_session_guard.py

def test_transcript_has_limit_error_detects_phrase(tmp_path):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        '{"type":"system","subtype":"init"}\n'
        '{"type":"result","is_error":true,"result":"Claude usage limit reached"}\n'
    )
    assert session_guard.transcript_has_limit_error(jsonl) is True


def test_transcript_has_limit_error_returns_false_on_clean_run(tmp_path):
    jsonl = tmp_path / "t.jsonl"
    jsonl.write_text(
        '{"type":"result","is_error":false,"result":"flag{ok}"}\n'
    )
    assert session_guard.transcript_has_limit_error(jsonl) is False


def test_transcript_has_limit_error_missing_file_returns_false(tmp_path):
    assert session_guard.transcript_has_limit_error(tmp_path / "nope.jsonl") is False


def test_transcript_has_limit_error_scans_only_tail(tmp_path):
    """Large transcripts: only the last 64KB is scanned, keeping the call cheap."""
    jsonl = tmp_path / "t.jsonl"
    # 200 KB of noise, then the error phrase at the very end.
    jsonl.write_text("x" * 200_000 + "\n5-hour limit reached\n")
    assert session_guard.transcript_has_limit_error(jsonl) is True
```

- [ ] **Step 2: Run tests**

Run: `cd <repo-root> && pytest tests/unit/test_session_guard.py -v`
Expected: all tests pass (impl already landed in Task 1).

- [ ] **Step 3: Commit**

```bash
cd <repo-root>
git add tests/unit/test_session_guard.py
git commit -m "test(session-guard): cover reactive transcript scan"
```

---

## Task 3: models.py — add `skipped_limit` status

**Files:**
- Modify: `hydra/models.py:7`
- Test: `tests/unit/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_models.py`:

```python
def test_status_literal_includes_skipped_limit():
    """Orchestrator emits skipped_limit when aborting a batch mid-flight."""
    from hydra.models import Result
    from hydra.usage import Usage
    r = Result(
        name="x", status="skipped_limit", flag=None, duration_s=0.0,
        started_at="2026-04-17T19:00:00Z", finished_at="2026-04-17T19:00:00Z",
        worker_exit_code=-2, work_dir="/tmp/x",
        reason="Claude session quota exceeded",
        usage=Usage(),
    )
    assert r.status == "skipped_limit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd <repo-root> && pytest tests/unit/test_models.py -v`
Expected: dataclass accepts any string at runtime so this passes on dynamic, but type checking would flag it. The test asserts the literal is documented; ensure the Status union is extended.

Actually since Python `Literal` doesn't enforce at runtime, this test will pass even without the change. Skip to Step 3 directly.

- [ ] **Step 3: Update `hydra/models.py:7`**

Replace:

```python
Status = Literal["solved", "failed", "timeout", "error", "solved_uncertain"]
```

with:

```python
Status = Literal[
    "solved",
    "failed",
    "timeout",
    "error",
    "solved_uncertain",
    "skipped_limit",
]
```

- [ ] **Step 4: Run the whole test suite to confirm nothing regressed**

Run: `cd <repo-root> && pytest tests/unit -v -x`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
cd <repo-root>
git add hydra/models.py tests/unit/test_models.py
git commit -m "feat(models): add skipped_limit status"
```

---

## Task 4: orchestrator — wire proactive + reactive guards

Inject guard behavior into `Orchestrator` with three touch points:

1. Config fields `session_pct_cap: float = 95.0` and `session_check_enabled: bool = True`.
2. State: `self._limit_tripped: bool = False` and `self._limit_reason: str = ""`.
3. In `_safe_one`: short-circuit to a `skipped_limit` Result when already tripped, else before entering `_one` call the proactive guard. After `_one` returns (inside the same method), reactively scan the transcript of the workdir(s) produced.

The pass@k code path (`_pass_at_k`) fans out N attempts per challenge — we check the guard once *before* fanning out, not per attempt. If the check trips mid-attempt (e.g., attempt 1 returns, transcript shows limit), remaining challenges in the batch see the trip; the in-flight pass@k siblings continue normally (they're already billed for).

**Files:**
- Modify: `hydra/orchestrator.py`
- Test: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_orchestrator.py`:

```python
async def test_session_guard_skips_remaining_when_cap_exceeded(tmp_path, monkeypatch):
    """When ccusage reports >= pct_cap, remaining challenges are recorded
    as skipped_limit and worker is never invoked for them."""
    from hydra.docker_worker import WorkerResult

    call_count = {"n": 0}
    async def counting_worker(*args, **kwargs):
        call_count["n"] += 1
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout=f"FLAG: flag{{{kwargs['name']}}}\n",
            stderr="", timed_out=False, duration_s=0.01,
        )
    monkeypatch.setattr("hydra.orchestrator.run_worker", counting_worker)

    # Guard trips immediately (before first worker call).
    monkeypatch.setattr(
        "hydra.orchestrator.session_guard.fetch_active_block",
        lambda: {
            "endTime": "2026-04-17T21:00:00.000Z",
            "tokenLimitStatus": {
                "limit": 100, "projectedUsage": 99,
                "percentUsed": 99.0, "status": "exceeded",
            },
        },
    )

    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([
        Challenge(name="a", description="x"),
        Challenge(name="b", description="y"),
    ])
    assert call_count["n"] == 0, "worker must not be invoked after guard trips"
    assert [r.status for r in writer.appended] == ["skipped_limit", "skipped_limit"]
    for r in writer.appended:
        assert "session" in (r.reason or "").lower()


async def test_reactive_transcript_scan_trips_guard(tmp_path, monkeypatch):
    """Worker whose transcript contains limit-error phrase trips the guard
    for subsequent challenges even without a proactive ccusage signal."""
    import json as _json
    from hydra.docker_worker import WorkerResult

    order = {"n": 0}
    async def worker(*args, **kwargs):
        wd = kwargs["workdir"]
        (wd / "logs").mkdir(parents=True, exist_ok=True)
        my_idx = order["n"]
        order["n"] += 1
        transcript = wd / "logs" / "claude.stdout.jsonl"
        if my_idx == 0:
            # First challenge hits the wall — transcript contains limit error.
            transcript.write_text(
                _json.dumps({"type": "result", "is_error": True,
                             "result": "Claude usage limit reached"}) + "\n"
            )
            return WorkerResult(
                name=kwargs["name"], exit_code=1,
                stdout="", stderr="limit", timed_out=False, duration_s=0.01,
            )
        # Subsequent challenges must not run.
        raise AssertionError("worker called after limit tripped")
    monkeypatch.setattr("hydra.orchestrator.run_worker", worker)
    # Proactive check returns None so only reactive path fires.
    monkeypatch.setattr(
        "hydra.orchestrator.session_guard.fetch_active_block", lambda: None,
    )

    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([
        Challenge(name="a", description="x"),
        Challenge(name="b", description="y"),
    ])
    by_name = {r.name: r.status for r in writer.appended}
    assert by_name["a"] == "error"  # the run that tripped it
    assert by_name["b"] == "skipped_limit"


async def test_session_check_disabled_never_skips(tmp_path, monkeypatch):
    from hydra.docker_worker import WorkerResult

    async def worker(*args, **kwargs):
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout=f"FLAG: flag{{{kwargs['name']}}}\n",
            stderr="", timed_out=False, duration_s=0.01,
        )
    monkeypatch.setattr("hydra.orchestrator.run_worker", worker)
    # Even a tripped ccusage would be ignored.
    def _boom():
        raise AssertionError("fetch_active_block must not be called when disabled")
    monkeypatch.setattr(
        "hydra.orchestrator.session_guard.fetch_active_block", _boom,
    )

    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        session_check_enabled=False,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "solved"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <repo-root> && pytest tests/unit/test_orchestrator.py::test_session_guard_skips_remaining_when_cap_exceeded tests/unit/test_orchestrator.py::test_reactive_transcript_scan_trips_guard tests/unit/test_orchestrator.py::test_session_check_disabled_never_skips -v`
Expected: `AttributeError: ... session_check_enabled` and import failures for `session_guard`.

- [ ] **Step 3: Update `hydra/orchestrator.py`**

Edit the top of the file to import `session_guard`:

```python
from hydra import session_guard
```

Extend `OrchestratorConfig` (after `attempts: int = 1` line):

```python
    session_pct_cap: float = 95.0
    session_check_enabled: bool = True
```

Extend `Orchestrator.__init__` — after `self._results: list[Result] = []`:

```python
        self._limit_tripped: bool = False
        self._limit_reason: str = ""
```

Rewrite `_safe_one` to short-circuit on trip and proactively check before dispatch:

```python
    async def _safe_one(self, c: Challenge) -> None:
        started = _now_iso()
        # Short-circuit: a previous worker already tripped the guard.
        if self._limit_tripped:
            await self._record_skipped_limit(c, started=started)
            return
        # Proactive check — query ccusage before spending any tokens.
        if self.cfg.session_check_enabled:
            block = session_guard.fetch_active_block()
            if block is not None:
                abort, reason = session_guard.should_abort(
                    block, pct_cap=self.cfg.session_pct_cap,
                )
                if abort:
                    self._limit_tripped = True
                    self._limit_reason = reason
                    await self._record_skipped_limit(c, started=started)
                    return
        try:
            await self._one(c, started=started)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            tb = traceback.format_exc()
            wd = self.cfg.runs_dir / c.name
            r = Result(
                name=c.name,
                status="error",
                flag=None,
                duration_s=0.0,
                started_at=started,
                finished_at=_now_iso(),
                worker_exit_code=-1,
                work_dir=str(wd),
                reason=f"orchestrator exception: {type(e).__name__}: {e}\n{tb[-800:]}",
            )
            self._results.append(r)
            self.writer.append(r)
            try:
                write_failure_md(c, r, work_dir=wd, failures_dir=self.cfg.failures_dir)
            except Exception:
                pass
            await self._emit_status(r)
```

Add the new helper on `Orchestrator`:

```python
    async def _record_skipped_limit(self, c: Challenge, *, started: str) -> None:
        reason = self._limit_reason or "Claude session limit reached"
        wd = self.cfg.runs_dir / c.name
        r = Result(
            name=c.name,
            status="skipped_limit",
            flag=None,
            duration_s=0.0,
            started_at=started,
            finished_at=_now_iso(),
            worker_exit_code=-2,
            work_dir=str(wd),
            reason=f"batch aborted: {reason}",
        )
        self._results.append(r)
        self.writer.append(r)
        await self._emit_status(r)
```

Add reactive scan at the end of `_one`, right after `parse_usage_dir` but before building the Result — OR right after appending. Cleanest: after `self.writer.append(r)` and before `_emit_status`:

In `_one`, change:

```python
        self._results.append(r)
        self.writer.append(r)
        if status != "solved":
            write_failure_md(c, r, work_dir=wd, failures_dir=self.cfg.failures_dir)
        await self._emit_status(r)
```

to:

```python
        self._results.append(r)
        self.writer.append(r)
        if status != "solved":
            write_failure_md(c, r, work_dir=wd, failures_dir=self.cfg.failures_dir)
        # Reactive: the transcript of the run that just finished may contain
        # a limit-error phrase even if ccusage hadn't ticked over yet.
        if not self._limit_tripped and self.cfg.session_check_enabled:
            log_file = wd / "logs" / "claude.stdout.jsonl"
            if session_guard.transcript_has_limit_error(log_file):
                self._limit_tripped = True
                self._limit_reason = (
                    "limit-error phrase detected in Claude transcript"
                )
        await self._emit_status(r)
```

Update `_status_line` to give `skipped_limit` a distinctive glyph:

```python
def _status_line(r: Result) -> str:
    if r.status == "solved":
        sym = "✓"
    elif r.status == "skipped_limit":
        sym = "-"
    else:
        sym = "✗"
    detail = r.flag if r.status == "solved" else f"({r.reason or r.status})"
    cost = f", ${r.usage.cost_usd:.2f}" if r.usage.cost_usd else ""
    return f"{sym} {r.name:24s} → {detail} ({r.duration_s:.1f}s{cost})"
```

- [ ] **Step 4: Run the new tests**

Run: `cd <repo-root> && pytest tests/unit/test_orchestrator.py -v`
Expected: all pass. The three new tests + every pre-existing orchestrator test.

- [ ] **Step 5: Commit**

```bash
cd <repo-root>
git add hydra/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(orchestrator): skip remaining challenges on session-limit trip"
```

---

## Task 5: failures.py — segregate skipped_limit in summary

`write_failures_summary` currently groups `"failed", "timeout", "error"` into one table. `skipped_limit` is categorically different (not a failure — a quota abort) and should appear in a separate section so postmortems don't re-run them.

**Files:**
- Modify: `hydra/failures.py:62-78`
- Test: `tests/unit/test_failures.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_failures.py` (create helper `_mk_result` if not present):

```python
def test_summary_segregates_skipped_limit(tmp_path):
    from hydra.failures import write_failures_summary
    from hydra.models import Result

    def _r(name, status, reason=None):
        return Result(
            name=name, status=status, flag=None, duration_s=1.0,
            started_at="x", finished_at="y",
            worker_exit_code=0, work_dir="/w", reason=reason,
        )

    results = [
        _r("solved1", "solved"),
        _r("fail1", "failed", "no flag"),
        _r("skip1", "skipped_limit", "batch aborted: quota 99%"),
        _r("skip2", "skipped_limit", "batch aborted: quota 99%"),
    ]
    path = write_failures_summary(results, failures_dir=tmp_path)
    text = path.read_text()
    # Failure table contains only true failures.
    assert "fail1" in text
    assert "solved1" not in text
    # Skipped section exists and lists the skipped names.
    assert "Skipped due to session limit" in text
    assert "skip1" in text
    assert "skip2" in text
    # Skipped entries NOT in the failing table.
    header_idx = text.index("| Challenge | Status |")
    skipped_idx = text.index("Skipped due to session limit")
    failing_table = text[header_idx:skipped_idx]
    assert "skip1" not in failing_table
```

- [ ] **Step 2: Run the test**

Run: `cd <repo-root> && pytest tests/unit/test_failures.py::test_summary_segregates_skipped_limit -v`
Expected: FAIL — current summary dumps skipped_limit nowhere.

- [ ] **Step 3: Update `hydra/failures.py`**

Replace `write_failures_summary` with:

```python
def write_failures_summary(results: list[Result], *, failures_dir: Path) -> Path:
    failures_dir.mkdir(parents=True, exist_ok=True)
    failing = [r for r in results if r.status in ("failed", "timeout", "error")]
    skipped = [r for r in results if r.status == "skipped_limit"]
    summary_path = failures_dir / "SUMMARY.md"
    lines = [
        f"# {len(failing)} failures out of {len(results)}",
        "",
        "| Challenge | Status | Duration | Reason |",
        "|-----------|--------|----------|--------|",
    ]
    for r in failing:
        reason = _table_cell(r.reason or "—")[:80]
        name = _table_cell(r.name)
        status = _table_cell(r.status)
        lines.append(f"| {name} | {status} | {r.duration_s:.1f}s | {reason} |")
    if skipped:
        lines += [
            "",
            f"## Skipped due to session limit ({len(skipped)})",
            "",
            "These challenges were never dispatched — the Claude session "
            "quota was hit mid-batch. Re-run after the 5-hour window resets.",
            "",
            "| Challenge | Reason |",
            "|-----------|--------|",
        ]
        for r in skipped:
            reason = _table_cell(r.reason or "—")[:100]
            name = _table_cell(r.name)
            lines.append(f"| {name} | {reason} |")
    summary_path.write_text("\n".join(lines) + "\n")
    return summary_path
```

- [ ] **Step 4: Run tests**

Run: `cd <repo-root> && pytest tests/unit/test_failures.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd <repo-root>
git add hydra/failures.py tests/unit/test_failures.py
git commit -m "feat(failures): segregate skipped_limit from failure summary"
```

---

## Task 6: CLI — expose `--session-pct-cap` and `--no-session-check`

`hydra/cli.py` has three wiring layers: `build_parser()` (argparse), `ResolvedConfig` dataclass at line 19, `resolve_config()` at line 80 that copies `ns → ResolvedConfig`, and `_run()` at line 242 that copies `ResolvedConfig → OrchestratorConfig`. Update all four.

**Files:**
- Modify: `hydra/cli.py:39-78` (parser), `hydra/cli.py:19-37` (ResolvedConfig), `hydra/cli.py:85-102` (resolve_config), `hydra/cli.py:242-254` (OrchestratorConfig build)
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:

```python
def test_parser_session_flag_defaults():
    p = build_parser()
    ns = p.parse_args(["chal.json"])
    assert ns.session_pct_cap == 95.0
    assert ns.session_check is True


def test_parser_session_flag_overrides():
    p = build_parser()
    ns = p.parse_args([
        "chal.json",
        "--session-pct-cap", "90.0",
        "--no-session-check",
    ])
    assert ns.session_pct_cap == 90.0
    assert ns.session_check is False


def test_resolve_config_carries_session_flags(tmp_path, monkeypatch):
    _patch_default_creds(monkeypatch, tmp_path, exists=True, logged_in=True)
    p = build_parser()
    ns = p.parse_args([
        "chal.json",
        "--session-pct-cap", "80.0",
        "--no-session-check",
    ])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.session_pct_cap == 80.0
    assert cfg.session_check_enabled is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd <repo-root> && pytest tests/unit/test_cli.py -v`
Expected: FAIL with `unrecognized arguments: --session-pct-cap` and (for Step 3) attribute errors.

- [ ] **Step 3: Update `build_parser()` in `hydra/cli.py`**

Insert the two flags between the existing `--use-api-key` block (line 73-77) and `return p` (line 78):

```python
    p.add_argument(
        "--session-pct-cap", type=float, default=95.0,
        help=(
            "Abort the batch when ccusage reports the active 5h block is "
            "≥ this percent of the plan's token limit. Default: 95.0."
        ),
    )
    p.add_argument(
        "--no-session-check",
        dest="session_check", action="store_false", default=True,
        help="Disable proactive + reactive Claude session-limit guards.",
    )
```

- [ ] **Step 4: Extend `ResolvedConfig` in `hydra/cli.py:19-37`**

After `attempts: int = 1` (line 37), add:

```python
    session_pct_cap: float = 95.0
    session_check_enabled: bool = True
```

- [ ] **Step 5: Update `resolve_config()` in `hydra/cli.py:85-102`**

After the `attempts=ns.attempts,` line (line 101), add:

```python
        session_pct_cap=ns.session_pct_cap,
        session_check_enabled=ns.session_check,
```

- [ ] **Step 6: Update `OrchestratorConfig(...)` build in `hydra/cli.py:242-254`**

After `attempts=cfg.attempts,` (line 253), add:

```python
        session_pct_cap=cfg.session_pct_cap,
        session_check_enabled=cfg.session_check_enabled,
```

- [ ] **Step 7: Run tests**

Run: `cd <repo-root> && pytest tests/unit/test_cli.py -v && pytest tests/unit -x`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
cd <repo-root>
git add hydra/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): --session-pct-cap and --no-session-check flags"
```

---

## Verification Checklist (run after Task 6)

- [ ] `pytest tests/unit -v` — every test passes.
- [ ] `pytest tests/integration -v` — integration pipeline still green.
- [ ] Smoke-run the CLI end-to-end on a known-easy challenge with `--session-pct-cap 0.1` and confirm every challenge is reported as `skipped_limit` (the guard trips immediately since any active block exceeds 0.1%).
- [ ] Verify `failures/SUMMARY.md` has the new "Skipped due to session limit" section populated.
- [ ] Revert the 0.1% cap to default and confirm normal solve behavior returns.
