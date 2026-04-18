# Watchdog + Pre-Commit Flag Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two deterministic (zero-token) supervision layers to Hydra — a per-worker Watchdog that pre-empts ruinous runs before they waste tokens or get OOM-killed, and a Pre-Commit Flag Gate that blocks malformed / partial / prefix-mismatched flags from being written to `flags.json`.

**Architecture:** Two independent subsystems sharing the orchestrator. `Watchdog` is an `asyncio.Task` per worker that tails `logs/claude.stdout.jsonl`, polls `docker stats` for memory, and returns a `KillReason` when a deterministic trigger fires. Orchestrator runs it concurrently with `run_worker` via `asyncio.wait(..., FIRST_COMPLETED)`; if watchdog wins the race, orchestrator asks the existing `_docker_stop` helper to stop the container and marks the Result `failed` with a `watchdog:<code>` reason. `FlagGate` is a pure verdict function called between `extract_flag` and `writer.append`; REJECT drops the flag, WARN demotes to the existing `solved_uncertain`, ACCEPT is normal.

**Tech Stack:** Python 3.12+ (asyncio, stdlib only), pytest (existing test conventions), Docker CLI for container stats/stop (reuse `hydra.docker_worker` engine selection). No new runtime dependencies.

**Scope check:** Two subsystems. They share one edit point (`orchestrator._one`) and one edit to `Challenge`. The gate is small enough and the shared surface thin enough that splitting would create coordination overhead. Keep as one plan, with Part A (Gate) and Part B (Watchdog) clearly sectioned so they can be reviewed / merged independently.

---

## File Structure

**Create:**
- `hydra/flag_gate.py` (~90 lines) — pure `check(candidate, challenge, workdir) -> GateVerdict` function; `Verdict` enum; rule set
- `hydra/watchdog.py` (~260 lines) — `Watchdog` class; `KillReason` dataclass; jsonl tailer; docker-stats memory sampler; per-signal evaluator methods
- `tests/unit/test_flag_gate.py` — unit tests for every rule
- `tests/unit/test_watchdog.py` — unit tests per evaluator + end-to-end tail-loop test

**Modify:**
- `hydra/models.py:9-17` — add `expected_format`, `flag_prefix` optional fields to `Challenge`
- `hydra/normalize.py:37-73` — plumb new fields from input JSON
- `hydra/orchestrator.py:15-29, 94-154, 165-182` — `OrchestratorConfig` additions; `_attempt` wires the watchdog; `_one` calls `FlagGate` after extraction
- `hydra/docker_worker.py` — expose `_docker_stop` as public so orchestrator can reach it
- `hydra/cli.py:19-78, 80-102` — CLI flags for watchdog tunables; resolve them into `OrchestratorConfig`
- `tests/unit/test_orchestrator.py` — add tests for watchdog-kill path, gate-reject path, gate-warn path
- `tests/unit/test_normalize.py` — field passthrough test

---

## Part A: Pre-Commit Flag Gate

### Task A1: Add `expected_format` + `flag_prefix` to `Challenge`

**Files:**
- Modify: `hydra/models.py:9-17`
- Test: `tests/unit/test_models.py` (new test)

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_models.py`:
```python
from hydra.models import Challenge


def test_challenge_accepts_expected_format_and_prefix():
    c = Challenge(
        name="x",
        description="d",
        expected_format=r"HTB\{[^}]+\}",
        flag_prefix="HTB",
    )
    assert c.expected_format == r"HTB\{[^}]+\}"
    assert c.flag_prefix == "HTB"


def test_challenge_defaults_both_fields_to_none():
    c = Challenge(name="x", description="d")
    assert c.expected_format is None
    assert c.flag_prefix is None
```

- [ ] **Step 2: Run to confirm it fails**

```
.venv/bin/pytest tests/unit/test_models.py -v
```
Expected: `TypeError: Challenge.__init__() got an unexpected keyword argument 'expected_format'`.

- [ ] **Step 3: Add the fields**

Edit `hydra/models.py`, replace lines 9-17 with:
```python
@dataclass(frozen=True)
class Challenge:
    name: str
    description: str
    files: list[Path] = field(default_factory=list)
    remote: str | None = None
    hints: list[str] = field(default_factory=list)
    category: str | None = None
    points: int | None = None
    # Optional pre-commit-gate hints. `expected_format` is a regex the
    # whole flag must fullmatch. `flag_prefix` is the text before the
    # `{` — when set, a mismatched prefix is a REJECT (not a WARN).
    expected_format: str | None = None
    flag_prefix: str | None = None
```

- [ ] **Step 4: Run to confirm it passes**

```
.venv/bin/pytest tests/unit/test_models.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add hydra/models.py tests/unit/test_models.py
git commit -m "feat(models): Challenge.expected_format + flag_prefix fields"
```

---

### Task A2: Plumb the new fields through `normalize`

**Files:**
- Modify: `hydra/normalize.py:11-17, 37-73`
- Test: `tests/unit/test_normalize.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_normalize.py`:
```python
def test_normalize_passes_expected_format_and_prefix():
    from hydra.normalize import normalize_challenges

    raw = [{
        "name": "c",
        "description": "d",
        "expected_format": r"HTB\{[^}]+\}",
        "flag_prefix": "HTB",
    }]
    [c] = normalize_challenges(raw)
    assert c.expected_format == r"HTB\{[^}]+\}"
    assert c.flag_prefix == "HTB"


def test_normalize_omits_fields_when_absent():
    from hydra.normalize import normalize_challenges

    [c] = normalize_challenges([{"name": "c", "description": "d"}])
    assert c.expected_format is None
    assert c.flag_prefix is None
```

- [ ] **Step 2: Run to confirm it fails**

```
.venv/bin/pytest tests/unit/test_normalize.py::test_normalize_passes_expected_format_and_prefix -v
```
Expected: FAIL (fields not threaded through).

- [ ] **Step 3: Thread the fields**

Edit `hydra/normalize.py`. Add these constant lines right after `_POINTS_KEYS` (around line 17):
```python
_EXPECTED_FORMAT_KEYS = ("expected_format", "flag_format", "format")
_FLAG_PREFIX_KEYS = ("flag_prefix", "prefix")
```

Then in `_normalize_one` (end of function, replace the `return Challenge(...)` block):
```python
    expected_format = _first(raw, _EXPECTED_FORMAT_KEYS)
    flag_prefix = _first(raw, _FLAG_PREFIX_KEYS)
    return Challenge(
        name=safe_name(str(name)),
        description=str(desc),
        files=files,
        remote=_first(raw, _REMOTE_KEYS),
        hints=[str(h) for h in hints],
        category=_first(raw, _CAT_KEYS),
        points=int(points) if points is not None else None,
        expected_format=str(expected_format) if expected_format is not None else None,
        flag_prefix=str(flag_prefix) if flag_prefix is not None else None,
    )
```

- [ ] **Step 4: Run to confirm it passes**

```
.venv/bin/pytest tests/unit/test_normalize.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/normalize.py tests/unit/test_normalize.py
git commit -m "feat(normalize): thread expected_format + flag_prefix from input JSON"
```

---

### Task A3: Create `flag_gate.py` with its verdict surface

**Files:**
- Create: `hydra/flag_gate.py`
- Test: `tests/unit/test_flag_gate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_flag_gate.py`:
```python
from pathlib import Path

import pytest

from hydra.flag_gate import Verdict, check
from hydra.models import Challenge


def _ch(**kw) -> Challenge:
    base = {"name": "x", "description": "d"}
    base.update(kw)
    return Challenge(**base)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "probe.py").write_text("# scratch\n")
    return tmp_path


def test_accept_well_formed_flag(workdir):
    v = check("HTB{real_body_42}", _ch(flag_prefix="HTB"), workdir)
    assert v.verdict == Verdict.ACCEPT


def test_reject_unclosed_brace(workdir):
    # Real case from OT splash-array: `WANLAI{d0f2c4aa536a0d0ab`.
    v = check("WANLAI{d0f2c4aa536a0d0ab", _ch(flag_prefix="WANLAI"), workdir)
    assert v.verdict == Verdict.REJECT
    assert "brace" in v.reason.lower()


def test_reject_wrong_prefix(workdir):
    v = check("flag{got_this_one}", _ch(flag_prefix="HTB"), workdir)
    assert v.verdict == Verdict.REJECT
    assert "prefix" in v.reason.lower()


def test_reject_expected_format_mismatch(workdir):
    v = check(
        "WANLAI{zzz}",
        _ch(expected_format=r"WANLAI\{[0-9a-f]{32}\}"),
        workdir,
    )
    assert v.verdict == Verdict.REJECT
    assert "format" in v.reason.lower()


def test_reject_length_and_control_chars(workdir):
    short = check("x{}", _ch(), workdir)
    assert short.verdict == Verdict.REJECT
    control = check("flag{\x07bell}", _ch(), workdir)
    assert control.verdict == Verdict.REJECT


def test_warn_on_prior_knowledge_log(workdir):
    (workdir / "work" / "prior-knowledge.log").write_text("recalled creds\n")
    v = check("HTB{body}", _ch(flag_prefix="HTB"), workdir)
    assert v.verdict == Verdict.WARN
    assert "prior_knowledge" in v.reason


def test_warn_on_empty_scratch(tmp_path):
    v = check("HTB{body}", _ch(flag_prefix="HTB"), tmp_path)
    assert v.verdict == Verdict.WARN
    assert "no_scratch" in v.reason


def test_reject_beats_warn_when_both_trigger(workdir):
    v = check("not_a_flag", _ch(), workdir)
    assert v.verdict == Verdict.REJECT
```

- [ ] **Step 2: Run to confirm they fail**

```
.venv/bin/pytest tests/unit/test_flag_gate.py -v
```
Expected: `ModuleNotFoundError: No module named 'hydra.flag_gate'`.

- [ ] **Step 3: Implement the gate**

Create `hydra/flag_gate.py`:
```python
"""Pre-commit flag gate: veto partial/malformed/mismatched flags before
they land in flags.json. Pure function — zero tokens, zero network.

Runs between flag_extractor.extract_flag() and ResultsWriter.append(),
so a REJECT keeps `flags.json` clean and `--retry-failed` can re-pick
the challenge. WARN demotes status to the existing `solved_uncertain`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from hydra.models import Challenge

_MAX_BODY_LEN = 128
_MIN_BODY_LEN = 1
_STRUCT_RE = re.compile(r"^([A-Za-z0-9_]+)\{([^}]+)\}$")


class Verdict(str, Enum):
    ACCEPT = "accept"
    WARN = "warn"
    REJECT = "reject"


@dataclass(frozen=True)
class GateVerdict:
    verdict: Verdict
    reason: str | None = None


def check(candidate: str, challenge: Challenge, workdir: Path) -> GateVerdict:
    """Gate a flag candidate. REJECT > WARN > ACCEPT.

    REJECT rules are structural: if any fire, the candidate never
    reaches flags.json. WARN rules flag derivation-evidence problems;
    they demote to solved_uncertain so the human can double-check
    before submitting.
    """
    candidate = candidate.strip()

    # --- REJECT rules (structural / format) ---
    if "{" in candidate and not candidate.rstrip().endswith("}"):
        return GateVerdict(Verdict.REJECT, "unclosed brace in flag")
    m = _STRUCT_RE.fullmatch(candidate)
    if not m:
        return GateVerdict(Verdict.REJECT, "malformed: does not match PREFIX{body}")
    prefix, body = m.group(1), m.group(2)
    if len(body) < _MIN_BODY_LEN or len(body) > _MAX_BODY_LEN:
        return GateVerdict(Verdict.REJECT, f"length {len(body)} out of bounds")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in body):
        return GateVerdict(Verdict.REJECT, "control char in body")
    if any(c.isspace() for c in body):
        return GateVerdict(Verdict.REJECT, "whitespace in body")

    if challenge.expected_format:
        if not re.fullmatch(challenge.expected_format, candidate):
            return GateVerdict(
                Verdict.REJECT,
                f"format mismatch: expected {challenge.expected_format!r}",
            )

    if challenge.flag_prefix and prefix.lower() != challenge.flag_prefix.lower():
        return GateVerdict(
            Verdict.REJECT,
            f"prefix mismatch: got {prefix!r}, expected {challenge.flag_prefix!r}",
        )

    # --- WARN rules (derivation evidence) ---
    prior_log = workdir / "work" / "prior-knowledge.log"
    if prior_log.exists() and prior_log.stat().st_size > 0:
        return GateVerdict(
            Verdict.WARN,
            "prior_knowledge log present — route to verifier-specialist",
        )
    work_dir = workdir / "work"
    if not work_dir.is_dir() or not any(work_dir.iterdir()):
        return GateVerdict(
            Verdict.WARN,
            "no_scratch: agent produced flag without derivation artifacts",
        )

    return GateVerdict(Verdict.ACCEPT)
```

- [ ] **Step 4: Run to confirm all pass**

```
.venv/bin/pytest tests/unit/test_flag_gate.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/flag_gate.py tests/unit/test_flag_gate.py
git commit -m "feat(flag_gate): pre-commit accept/warn/reject verdict on flag candidates"
```

---

### Task A4: Wire `FlagGate` into orchestrator between extraction and status assignment

**Files:**
- Modify: `hydra/orchestrator.py:94-154`
- Test: `tests/unit/test_orchestrator.py` (add two tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_orchestrator.py` (above `test_skip_already_solved`):
```python
async def test_gate_rejects_unclosed_flag_keeps_it_out_of_flags_json(
    tmp_path, monkeypatch
):
    """flag.txt with an unclosed brace (the OT splash-array bug) must
    not propagate to flags.json; status becomes 'failed' so
    --retry-failed can re-pick it."""
    async def worker_partial_flag(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("WANLAI{d0f2c4aa536a0d0ab\n")
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="done", stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker_partial_flag)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="WANLAI")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
    assert "unclosed" in (r.reason or "").lower()


async def test_gate_warn_demotes_to_solved_uncertain(tmp_path, monkeypatch):
    """A flag produced with no /workspace/work scratch artifacts is
    derivation-suspect; gate WARN must demote to solved_uncertain while
    still recording the flag (user can verify)."""
    async def worker_no_scratch(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("HTB{some_body_here}\n")
        # deliberately no work/ dir
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="done", stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker_no_scratch)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="HTB")])
    [r] = writer.appended
    assert r.status == "solved_uncertain"
    assert r.flag == "HTB{some_body_here}"
    assert "no_scratch" in (r.reason or "")
```

- [ ] **Step 2: Run to confirm they fail**

```
.venv/bin/pytest tests/unit/test_orchestrator.py::test_gate_rejects_unclosed_flag_keeps_it_out_of_flags_json tests/unit/test_orchestrator.py::test_gate_warn_demotes_to_solved_uncertain -v
```
Expected: both FAIL — gate not wired.

- [ ] **Step 3: Wire the gate**

Edit `hydra/orchestrator.py`. First add import near line 8:
```python
from hydra.flag_gate import Verdict as GateVerdictEnum, check as gate_check
```

Then in `_one` (current lines 112-136), replace the status-assignment block with:
```python
        flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

        if wr.timed_out:
            status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
        elif flag:
            gate = gate_check(flag, c, wd)
            log_file = wd / "logs" / "claude.stdout.jsonl"
            if gate.verdict == GateVerdictEnum.REJECT:
                flag = None
                status, reason = "failed", f"flag_gate rejected: {gate.reason}"
            elif wr.exit_code == 137:
                status = "solved_uncertain"
                reason = (
                    "worker exited 137 (SIGKILL / OOM) — flag may be stale, "
                    "verify manually before submitting"
                )
            elif c.remote and not was_remote_contacted(log_file, c.remote):
                status = "solved_uncertain"
                reason = (
                    f"flag extracted but no evidence agent contacted remote "
                    f"{c.remote} — likely false positive from README/binary string"
                )
            elif gate.verdict == GateVerdictEnum.WARN:
                status = "solved_uncertain"
                reason = f"flag_gate warn: {gate.reason}"
            else:
                status, reason = "solved", None
        elif wr.exit_code != 0:
            status = "error"
            reason = (wr.stderr[-1024:] if wr.stderr else f"worker exited {wr.exit_code}")
        else:
            status, reason = "failed", "no flag recovered from stdout or flag.txt"
```

- [ ] **Step 4: Run new tests**

```
.venv/bin/pytest tests/unit/test_orchestrator.py -v
```
Expected: all PASS (existing 12+ tests plus the 2 new ones).

- [ ] **Step 5: Run the full suite**

```
.venv/bin/pytest -x
```
Expected: every test passes.

- [ ] **Step 6: Commit**

```
git add hydra/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(orchestrator): gate flag candidates before commit (REJECT/WARN/ACCEPT)"
```

---

## Part B: Sidecar Watchdog

### Task B1: Expose `_docker_stop` as a public helper

The watchdog needs to stop a running container when a kill signal fires. `docker_worker.py` already has `_docker_stop` for timeout handling — we just need it callable from `orchestrator.py`.

**Files:**
- Modify: `hydra/docker_worker.py` (rename the private helper)

- [ ] **Step 1: Rename the existing helper**

Edit `hydra/docker_worker.py`. Change `async def _docker_stop(` to `async def stop_container(`, then replace both existing call sites (`await _docker_stop(engine, container_name)`) with `await stop_container(engine, container_name)`.

- [ ] **Step 2: Run the worker tests**

```
.venv/bin/pytest tests/unit/test_docker_worker.py -v
```
Expected: all PASS (no behaviour change).

- [ ] **Step 3: Commit**

```
git add hydra/docker_worker.py
git commit -m "refactor(docker_worker): expose stop_container as public helper"
```

---

### Task B2: Scaffold `Watchdog` + `KillReason` + empty `run()` loop

**Files:**
- Create: `hydra/watchdog.py`
- Test: `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_watchdog.py`:
```python
import asyncio
import json
from pathlib import Path

import pytest

from hydra.watchdog import Watchdog, WatchdogConfig, KillReason


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
```

- [ ] **Step 2: Run to confirm import fails**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: `ModuleNotFoundError: No module named 'hydra.watchdog'`.

- [ ] **Step 3: Create the scaffold**

Create `hydra/watchdog.py`:
```python
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
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


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
```

- [ ] **Step 4: Run the cancellation test**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_run_returns_when_cancelled -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "feat(watchdog): scaffold Watchdog + KillReason + WatchdogConfig"
```

---

### Task B3: Jsonl tail reader + same-Bash-repeat detector

**Files:**
- Modify: `hydra/watchdog.py`
- Test: `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_watchdog.py`:
```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_kill_on_same_bash_repeat -v
```
Expected: `TimeoutError` — tail loop never returns.

- [ ] **Step 3: Implement tail reader + detector**

Replace `_tail_loop` in `hydra/watchdog.py` and add the helpers:
```python
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
```

- [ ] **Step 4: Run the tests**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "feat(watchdog): tail jsonl + same-Bash-prefix repeat detector"
```

---

### Task B4: Solver-variant proliferation detector

**Files:**
- Modify: `hydra/watchdog.py`
- Test: `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_watchdog.py`:
```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_kill_on_solver_variant_proliferation -v
```
Expected: FAIL.

- [ ] **Step 3: Implement the detector**

Add the module-level regex near the imports:
```python
_SOLVER_PATTERN = re.compile(r"/workspace/work/(solve|probe|exploit)\d+\.py$")
```

In `_on_event`, extend the tool_use handler to also branch on Write:
```python
            if block.get("name") == "Write":
                path = (block.get("input") or {}).get("file_path", "")
                reason = self._check_solver_spam(path)
                if reason:
                    return reason
```

Add the method:
```python
    def _check_solver_spam(self, file_path: str) -> KillReason | None:
        if not _SOLVER_PATTERN.search(file_path):
            return None
        self._state.solver_variants.add(file_path)
        if len(self._state.solver_variants) >= self.cfg.max_solver_variants:
            return KillReason(
                code="solver_spam",
                detail=f"{len(self._state.solver_variants)} solver variants written",
            )
        return None
```

- [ ] **Step 4: Run tests**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "feat(watchdog): solver/probe/exploit variant proliferation detector"
```

---

### Task B5: Cost-cap detector (stream accumulation from `usage` blocks)

**Files:**
- Modify: `hydra/watchdog.py`
- Test: `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_watchdog.py`:
```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_kill_on_cost_cap -v
```
Expected: FAIL.

- [ ] **Step 3: Implement the rate table and cost evaluator**

Add near the top of `hydra/watchdog.py`:
```python
# USD per million tokens. (input, output, cache_creation). cache_read is
# 10% of input. Fallback is opus (expensive side) so unknown models
# don't under-count.
_MODEL_RATES_USD_PER_MTOK: dict[str, tuple[float, float, float]] = {
    "claude-opus-4-7":            (15.0, 75.0, 18.75),
    "claude-opus-4-6":            (15.0, 75.0, 18.75),
    "claude-sonnet-4-6":          (3.0,  15.0, 3.75),
    "claude-haiku-4-5-20251001":  (1.0,  5.0,  1.25),
}
_DEFAULT_RATES = _MODEL_RATES_USD_PER_MTOK["claude-opus-4-7"]


def _cost_for(model: str, usage: dict) -> float:
    rates = _MODEL_RATES_USD_PER_MTOK.get(model, _DEFAULT_RATES)
    in_rate, out_rate, cache_rate = rates
    cache_read_rate = in_rate * 0.1
    it = int(usage.get("input_tokens") or 0)
    ot = int(usage.get("output_tokens") or 0)
    cc = int(usage.get("cache_creation_input_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    return (
        it * in_rate + ot * out_rate
        + cc * cache_rate + cr * cache_read_rate
    ) / 1_000_000
```

In `_on_event`, after the tool_use loop, add usage accumulation:
```python
        usage = msg.get("usage")
        mid = msg.get("id")
        if isinstance(usage, dict) and mid:
            # Streaming deltas for the same message id should overwrite,
            # not accumulate (same rule usage.py uses for per-message).
            self._msg_cost[mid] = _cost_for(self.model_name, usage)
            self._state.cost_usd = sum(self._msg_cost.values())
            if self._state.cost_usd >= self.cfg.cost_cap_usd:
                return KillReason(
                    code="cost_cap",
                    detail=(
                        f"${self._state.cost_usd:.2f} "
                        f">= ${self.cfg.cost_cap_usd:.2f}"
                    ),
                )
```

- [ ] **Step 4: Run tests**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "feat(watchdog): streaming cost cap via per-message usage + model rates"
```

---

### Task B6: Memory-pressure detector + `docker stats` sampler

**Files:**
- Modify: `hydra/watchdog.py`
- Test: `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_watchdog.py`:
```python
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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_kill_on_memory_pressure -v
```
Expected: FAIL — `_poll_loop` is a placeholder.

- [ ] **Step 3: Implement the mem check in `_poll_loop` and a sampler factory**

Replace `_poll_loop` in `hydra/watchdog.py`:
```python
    async def _poll_loop(self) -> KillReason:
        while True:
            await asyncio.sleep(self.cfg.poll_interval_s)
            try:
                pct = self.mem_sampler(self.container_name)
            except Exception:
                pct = None
            if pct is not None and pct >= self.cfg.mem_kill_pct:
                return KillReason(
                    code="oom_preempt",
                    detail=f"RSS {pct:.1f}% >= {self.cfg.mem_kill_pct:.1f}%",
                )
```

Append a public sampler factory (below the Watchdog class):
```python
def docker_mem_sampler(
    engine: str = "docker",
) -> Callable[[str], float | None]:
    """Return a blocking callable that runs `docker stats --no-stream`
    and parses the MemPerc column. Returns None when the container is
    gone or stats fails — don't treat 'unavailable' as pressure.
    """
    import subprocess

    def sample(container_name: str) -> float | None:
        try:
            out = subprocess.run(
                [engine, "stats", "--no-stream",
                 "--format", "{{.MemPerc}}", container_name],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if out.returncode != 0:
            return None
        s = (out.stdout or "").strip().rstrip("%")
        try:
            return float(s)
        except ValueError:
            return None

    return sample
```

- [ ] **Step 4: Run tests**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "feat(watchdog): docker-stats memory sampler + oom_preempt kill"
```

---

### Task B7: Idle-work detector (scratch stale + agent still tool-using)

**Files:**
- Modify: `hydra/watchdog.py`
- Test: `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_watchdog.py`:
```python
async def test_kill_on_idle_work(tmp_path: Path, monkeypatch):
    """work/ mtime unchanged past idle threshold + agent still writing
    tool_uses → kill before further burn."""
    import os
    jsonl = tmp_path / "claude.stdout.jsonl"
    jsonl.write_text("")
    (tmp_path / "work").mkdir()

    clock = {"t": 1000.0}
    monkeypatch.setattr("hydra.watchdog.time.monotonic", lambda: clock["t"])
    monkeypatch.setattr("hydra.watchdog.time.time", lambda: clock["t"])

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
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_kill_on_idle_work -v
```
Expected: FAIL — no idle check in the poll loop.

- [ ] **Step 3: Extend `_poll_loop`**

Edit `_poll_loop` in `hydra/watchdog.py`:
```python
    async def _poll_loop(self) -> KillReason:
        while True:
            await asyncio.sleep(self.cfg.poll_interval_s)
            try:
                pct = self.mem_sampler(self.container_name)
            except Exception:
                pct = None
            if pct is not None and pct >= self.cfg.mem_kill_pct:
                return KillReason(
                    code="oom_preempt",
                    detail=f"RSS {pct:.1f}% >= {self.cfg.mem_kill_pct:.1f}%",
                )
            reason = self._check_idle_work()
            if reason:
                return reason

    def _check_idle_work(self) -> KillReason | None:
        if self._state.last_tool_use_ts == 0.0:
            return None
        mono_now = time.monotonic()
        wall_now = time.time()
        try:
            mtime = self.work_dir.stat().st_mtime
        except FileNotFoundError:
            return None
        age = wall_now - mtime
        since_tool = mono_now - self._state.last_tool_use_ts
        if (
            age > self.cfg.idle_work_timeout_s
            and since_tool < self.cfg.poll_interval_s * 2
        ):
            return KillReason(
                code="idle_work",
                detail=(
                    f"work/ unchanged {int(age)}s "
                    f"while agent still active"
                ),
            )
        return None
```

- [ ] **Step 4: Run tests**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "feat(watchdog): idle-work detector (scratch stale + agent still producing)"
```

---

### Task B8: Wire `Watchdog` into `Orchestrator._attempt`

**Files:**
- Modify: `hydra/orchestrator.py:15-29, 94-154, 165-232`
- Test: `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_orchestrator.py`:
```python
async def test_watchdog_kill_overrides_worker_result(tmp_path, monkeypatch):
    """Watchdog returning a KillReason must override the worker's own
    WorkerResult: status = failed, reason = 'watchdog: <code> (...)',
    flag = None even if flag.txt happened to hold a candidate."""
    from hydra.watchdog import KillReason

    async def slow_worker(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("HTB{looks_good_but_loop_detected}\n")
        await asyncio.sleep(0.2)
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="", stderr="", timed_out=False, duration_s=0.2,
        )

    class InstantKillWatchdog:
        def __init__(self, *a, **kw): pass
        async def run(self) -> KillReason:
            return KillReason(code="bash_repeat", detail="test-triggered")

    async def no_op_stop(*args, **kwargs):
        return None

    monkeypatch.setattr("hydra.orchestrator.run_worker", slow_worker)
    monkeypatch.setattr("hydra.orchestrator.Watchdog", InstantKillWatchdog)
    monkeypatch.setattr("hydra.orchestrator.stop_container", no_op_stop)

    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog_enabled=True,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="HTB")])
    [r] = writer.appended
    assert r.status == "failed"
    assert r.flag is None
    assert "watchdog: bash_repeat" in (r.reason or "")
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_orchestrator.py::test_watchdog_kill_overrides_worker_result -v
```
Expected: `TypeError` — `OrchestratorConfig` has no `watchdog_enabled`.

- [ ] **Step 3: Extend `OrchestratorConfig`**

Edit `hydra/orchestrator.py`. Replace the `OrchestratorConfig` dataclass (lines 15-29):
```python
@dataclass
class OrchestratorConfig:
    parallel: int
    timeout_s: float
    model: str
    image: str
    runs_dir: Path
    failures_dir: Path
    prompt_volumes: dict[Path, str]
    credentials_dir: Path | None = None
    api_key: str | None = None
    container_cpus: int = 2
    container_memory: str = "8g"
    skip_names: set[str] = field(default_factory=set)
    attempts: int = 1  # pass@k: N parallel attempts per challenge, first flag wins
    # Watchdog tunables. `watchdog_enabled=False` skips construction
    # entirely (used by tests that don't need it and by `--no-watchdog`).
    watchdog_enabled: bool = True
    watchdog_cost_cap_usd: float = 10.0
    watchdog_mem_kill_pct: float = 90.0
    watchdog_max_same_bash_repeats: int = 3
    watchdog_max_solver_variants: int = 5
    watchdog_idle_work_timeout_s: float = 180.0
```

- [ ] **Step 4: Add the watchdog imports**

Add near the top of `hydra/orchestrator.py`:
```python
from hydra.watchdog import (
    Watchdog, WatchdogConfig, KillReason, docker_mem_sampler,
)
from hydra.docker_worker import stop_container
```

- [ ] **Step 5: Rewrite `_attempt` to co-run the watchdog**

Replace the current `_attempt` body (lines 165-182):
```python
    async def _attempt(
        self, c: Challenge, *, subpath: str | None
    ) -> tuple[Path, WorkerResult, KillReason | None]:
        """Run one solve attempt alongside a Watchdog. Returns
        (workdir, worker_result, kill_reason_or_None)."""
        wd = build_workdir(c, runs_dir=self.cfg.runs_dir, subpath=subpath)
        container_name = f"hydra-{c.name}"
        worker_task = asyncio.create_task(run_worker(
            name=c.name,
            workdir=wd,
            image=self.cfg.image,
            credentials_dir=self.cfg.credentials_dir,
            api_key=self.cfg.api_key,
            model=self.cfg.model,
            timeout_s=self.cfg.timeout_s,
            container_cpus=self.cfg.container_cpus,
            container_memory=self.cfg.container_memory,
            prompt_volumes=self.cfg.prompt_volumes,
        ))
        if not self.cfg.watchdog_enabled:
            wr = await worker_task
            return wd, wr, None

        jsonl = wd / "logs" / "claude.stdout.jsonl"
        watchdog = Watchdog(
            container_name=container_name,
            jsonl_path=jsonl,
            work_dir=wd / "work",
            config=WatchdogConfig(
                cost_cap_usd=self.cfg.watchdog_cost_cap_usd,
                mem_kill_pct=self.cfg.watchdog_mem_kill_pct,
                max_same_bash_repeats=self.cfg.watchdog_max_same_bash_repeats,
                max_solver_variants=self.cfg.watchdog_max_solver_variants,
                idle_work_timeout_s=self.cfg.watchdog_idle_work_timeout_s,
            ),
            mem_sampler=docker_mem_sampler(),
            model_name=self.cfg.model,
        )
        wd_task = asyncio.create_task(watchdog.run())

        done, _pending = await asyncio.wait(
            [worker_task, wd_task], return_when=asyncio.FIRST_COMPLETED,
        )
        if wd_task in done:
            kill_reason = wd_task.result()
            # Stop the container so the worker unblocks promptly.
            await stop_container("docker", container_name)
            try:
                wr = await asyncio.wait_for(worker_task, timeout=30)
            except TimeoutError:
                worker_task.cancel()
                try:
                    wr = await worker_task
                except asyncio.CancelledError:
                    wr = WorkerResult(
                        name=c.name, exit_code=-9,
                        stdout="", stderr="",
                        timed_out=False, duration_s=0.0,
                    )
            return wd, wr, kill_reason
        # Worker finished first — cancel the watchdog.
        wd_task.cancel()
        try:
            await wd_task
        except asyncio.CancelledError:
            pass
        wr = worker_task.result()
        return wd, wr, None
```

- [ ] **Step 6: Update the unpacking in `_one`**

In `_one`, replace the attempt-unpacking block:
```python
            if self.cfg.attempts <= 1:
                async with self._sem:
                    wd, wr, kill = await self._attempt(c, subpath=None)
            else:
                wd, wr, kill = await self._pass_at_k(c)
```

Insert the kill override at the top of the flag-resolution block (right after `flag = extract_flag(...)`):
```python
        flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

        if kill is not None:
            # Watchdog wins over everything else — even if flag.txt
            # holds a candidate, a tripped watchdog means the run
            # wasn't healthy.
            flag = None
            status = "failed"
            reason = str(kill)
        elif wr.timed_out:
            status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
        elif flag:
            # ...existing gate + remote-contact logic stays as-is...
```

- [ ] **Step 7: Update `_pass_at_k` to return the 3-tuple**

Replace the winner-loop and return paths:
```python
    async def _pass_at_k(
        self, c: Challenge
    ) -> tuple[Path, WorkerResult, KillReason | None]:
        """Fan out N attempts. First one to produce a clean flag wins;
        cancel the rest. Watchdog kills make an attempt ineligible for
        winner status (kill reason propagates on full-fleet kill)."""
        assert self._sem is not None
        k = self.cfg.attempts

        async def one_slotted(idx: int):
            async with self._sem:
                return await self._attempt(c, subpath=f"a{idx + 1}")

        tasks = [asyncio.create_task(one_slotted(i)) for i in range(k)]
        pending = set(tasks)
        winner: tuple[Path, WorkerResult, str] | None = None
        last: tuple[Path, WorkerResult, KillReason | None] | None = None

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED,
                )
                for t in done:
                    try:
                        wd, wr, kill = t.result()
                    except asyncio.CancelledError:
                        continue
                    last = (wd, wr, kill)
                    flag = extract_flag(
                        flag_file=wd / "flag.txt", stdout=wr.stdout
                    )
                    if flag and not wr.timed_out and kill is None:
                        winner = (wd, wr, flag)
                        break
                if winner:
                    break
        finally:
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        if winner:
            top_flag = self.cfg.runs_dir / c.name / "flag.txt"
            top_flag.write_text(winner[2] + "\n")
            return winner[0], winner[1], None
        assert last is not None, "all pass@k attempts cancelled without completing"
        return last
```

- [ ] **Step 8: Run the orchestrator tests**

```
.venv/bin/pytest tests/unit/test_orchestrator.py -v
```
Expected: all PASS (existing tests + the new watchdog-kill test).

- [ ] **Step 9: Run the full suite**

```
.venv/bin/pytest -x
```
Expected: every test passes.

- [ ] **Step 10: Commit**

```
git add hydra/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat(orchestrator): co-run Watchdog with worker; kill-reason overrides status"
```

---

### Task B9: CLI flags for watchdog tunables

**Files:**
- Modify: `hydra/cli.py:19-78, 80-102`
- Test: `tests/unit/test_cli.py` (new tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_cli.py`:
```python
def test_cli_parses_watchdog_flags():
    from hydra.cli import build_parser

    ns = build_parser().parse_args(["chal.json", "--no-watchdog"])
    assert ns.no_watchdog is True

    ns = build_parser().parse_args([
        "chal.json",
        "--watchdog-cost-cap", "3.5",
        "--watchdog-mem-kill-pct", "75",
    ])
    assert ns.watchdog_cost_cap == 3.5
    assert ns.watchdog_mem_kill_pct == 75.0


def test_resolve_config_plumbs_watchdog_to_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    from hydra.cli import build_parser, resolve_config

    ns = build_parser().parse_args([
        "chal.json", "--use-api-key",
        "--watchdog-cost-cap", "2.0",
        "--watchdog-mem-kill-pct", "80.5",
        "--watchdog-max-bash-repeats", "5",
        "--watchdog-max-solver-variants", "8",
        "--watchdog-idle-work-timeout", "300",
    ])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.watchdog_enabled is True
    assert cfg.watchdog_cost_cap_usd == 2.0
    assert cfg.watchdog_mem_kill_pct == 80.5
    assert cfg.watchdog_max_same_bash_repeats == 5
    assert cfg.watchdog_max_solver_variants == 8
    assert cfg.watchdog_idle_work_timeout_s == 300.0
```

- [ ] **Step 2: Run to confirm failure**

```
.venv/bin/pytest tests/unit/test_cli.py::test_cli_parses_watchdog_flags -v
```
Expected: FAIL.

- [ ] **Step 3: Extend `ResolvedConfig`**

Edit `hydra/cli.py` around line 19:
```python
@dataclass
class ResolvedConfig:
    challenges_path: str
    parallel: int | None
    timeout: int
    model: str
    runs_dir: Path
    results_path: Path
    jsonl_path: Path
    flags_path: Path
    failures_dir: Path
    retry_failed: bool
    only_filter: set[str] | None
    dry_run: bool
    rebuild_image: bool
    credentials_dir: Path | None = None
    api_key: str | None = None
    image: str = "hydra-worker"
    attempts: int = 1
    watchdog_enabled: bool = True
    watchdog_cost_cap_usd: float = 10.0
    watchdog_mem_kill_pct: float = 90.0
    watchdog_max_same_bash_repeats: int = 3
    watchdog_max_solver_variants: int = 5
    watchdog_idle_work_timeout_s: float = 180.0
```

- [ ] **Step 4: Add the argparse flags**

In `build_parser`, before the final `return p`:
```python
    p.add_argument(
        "--no-watchdog", action="store_true",
        help="Disable the deterministic sidecar watchdog. Use when "
             "debugging the agent itself and you don't want auto-kill.",
    )
    p.add_argument(
        "--watchdog-cost-cap", type=float, default=10.0, metavar="USD",
        help="Kill a worker once estimated token cost exceeds this cap.",
    )
    p.add_argument(
        "--watchdog-mem-kill-pct", type=float, default=90.0, metavar="PCT",
        help="Kill cleanly when container RSS reaches this percent of "
             "its --memory limit (pre-empts kernel OOM).",
    )
    p.add_argument(
        "--watchdog-max-bash-repeats", type=int, default=3, metavar="N",
        help="Kill when the same Bash command prefix fires N+ times.",
    )
    p.add_argument(
        "--watchdog-max-solver-variants", type=int, default=5, metavar="N",
        help="Kill when the agent writes more than N files matching "
             "/workspace/work/{solve,probe,exploit}NNN.py.",
    )
    p.add_argument(
        "--watchdog-idle-work-timeout", type=float, default=180.0, metavar="S",
        help="Kill when workdir/work/ mtime is stale longer than S "
             "seconds while the agent is still emitting tool_uses.",
    )
```

- [ ] **Step 5: Plumb into `resolve_config` and the orchestrator**

In `resolve_config`, extend the return:
```python
    return ResolvedConfig(
        # ...existing fields...
        attempts=ns.attempts,
        watchdog_enabled=not ns.no_watchdog,
        watchdog_cost_cap_usd=ns.watchdog_cost_cap,
        watchdog_mem_kill_pct=ns.watchdog_mem_kill_pct,
        watchdog_max_same_bash_repeats=ns.watchdog_max_bash_repeats,
        watchdog_max_solver_variants=ns.watchdog_max_solver_variants,
        watchdog_idle_work_timeout_s=ns.watchdog_idle_work_timeout,
    )
```

In `_run` where `OrchestratorConfig` is constructed:
```python
    orch_cfg = OrchestratorConfig(
        parallel=parallel,
        timeout_s=cfg.timeout,
        model=cfg.model,
        image=cfg.image,
        credentials_dir=cfg.credentials_dir,
        api_key=cfg.api_key,
        runs_dir=cfg.runs_dir,
        failures_dir=cfg.failures_dir,
        prompt_volumes=_prompt_volumes(),
        skip_names=skip,
        attempts=cfg.attempts,
        watchdog_enabled=cfg.watchdog_enabled,
        watchdog_cost_cap_usd=cfg.watchdog_cost_cap_usd,
        watchdog_mem_kill_pct=cfg.watchdog_mem_kill_pct,
        watchdog_max_same_bash_repeats=cfg.watchdog_max_same_bash_repeats,
        watchdog_max_solver_variants=cfg.watchdog_max_solver_variants,
        watchdog_idle_work_timeout_s=cfg.watchdog_idle_work_timeout_s,
    )
```

- [ ] **Step 6: Run CLI tests**

```
.venv/bin/pytest tests/unit/test_cli.py -v
```
Expected: all PASS.

- [ ] **Step 7: Run full suite**

```
.venv/bin/pytest
```
Expected: every test passes.

- [ ] **Step 8: Commit**

```
git add hydra/cli.py tests/unit/test_cli.py
git commit -m "feat(cli): --no-watchdog + per-signal tunables"
```

---

### Task B10: Integration smoke — watchdog kills in a fake-docker pipeline

**Files:**
- Modify: `tests/integration/test_pipeline.py`
- Modify: `tests/integration/fake_docker.py` (extend if needed)

- [ ] **Step 1: Inspect the fake shim**

Read `tests/integration/fake_docker.py` to learn its scenario schema.

- [ ] **Step 2: Extend the shim (only if needed)**

If the shim doesn't already emit a list of jsonl events with a trailing sleep, add this handling right before the final exit:
```python
events = scenario.get("emit_jsonl_events") or []
for e in events:
    sys.stdout.write(json.dumps(e) + "\n")
    sys.stdout.flush()
    time.sleep(0.05)
sleep_s = scenario.get("then_sleep_s")
if sleep_s:
    time.sleep(float(sleep_s))
```

- [ ] **Step 3: Write the integration test**

Append to `tests/integration/test_pipeline.py`:
```python
import json


def test_watchdog_kills_looping_agent(fake_docker, tmp_path):
    """End-to-end: fake-docker agent emits 3 identical Bash commands
    then stalls. Watchdog must kill; orchestrator records `failed`
    with a `watchdog:` reason; flags.json stays clean."""
    scenario = {
        "emit_jsonl_events": [
            {
                "type": "assistant",
                "message": {
                    "id": f"msg_{i}",
                    "content": [{
                        "type": "tool_use",
                        "name": "Bash",
                        "input": {"command": "curl http://10.0.0.1/probe"},
                    }],
                    "usage": {"input_tokens": 10, "output_tokens": 10,
                              "cache_read_input_tokens": 0,
                              "cache_creation_input_tokens": 0},
                },
            } for i in range(3)
        ],
        "then_sleep_s": 30,
        "exit_code": 0,
    }
    fake_docker.write_text(json.dumps(scenario))

    challenges_path = tmp_path / "chals.json"
    challenges_path.write_text(json.dumps(
        [{"name": "loopy", "description": "stub"}]
    ))

    from hydra.cli import main
    rc = main([
        str(challenges_path),
        "--use-api-key",
        "--timeout", "10",
        "--watchdog-max-bash-repeats", "3",
        "--watchdog-idle-work-timeout", "1",
        "--parallel", "1",
    ])
    assert rc == 1  # no solves
    results = json.loads((tmp_path / "chals" / "results.json").read_text())
    [r] = results["challenges"]
    assert r["status"] == "failed"
    assert r["reason"].startswith("watchdog:")
    flags = json.loads((tmp_path / "chals" / "flags.json").read_text())
    assert flags.get("loopy") is None
```

- [ ] **Step 4: Run the integration test**

```
.venv/bin/pytest tests/integration/test_pipeline.py::test_watchdog_kills_looping_agent -v
```
Expected: PASS.

- [ ] **Step 5: Run the full suite**

```
.venv/bin/pytest
```
Expected: all pass.

- [ ] **Step 6: Commit**

```
git add tests/integration/test_pipeline.py tests/integration/fake_docker.py
git commit -m "test(integration): watchdog kills looping agent end-to-end"
```

---

## Part C: Documentation

### Task C1: README + CLAUDE.md updates

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a "Safety rails" section to `README.md`**

Insert after the "Exploit discipline" section:
```markdown
## Safety rails

Hydra ships two deterministic supervision layers. Both run per-worker,
use zero tokens, and can be tuned via CLI flags.

### Watchdog (sidecar)

Runs alongside each worker container and tails
`runs/<name>/logs/claude.stdout.jsonl` for bad-behavior signals. Kills
the container before it blows its budget. Signals:

| Code | Trigger | CLI flag |
|---|---|---|
| `bash_repeat` | Same Bash command prefix fires N+ times | `--watchdog-max-bash-repeats` (default 3) |
| `solver_spam` | >N files written matching `work/{solve,probe,exploit}NNN.py` | `--watchdog-max-solver-variants` (default 5) |
| `cost_cap` | Estimated token cost exceeds cap | `--watchdog-cost-cap` (default $10) |
| `oom_preempt` | Container RSS ≥ X% of memory limit | `--watchdog-mem-kill-pct` (default 90%) |
| `idle_work` | `work/` unchanged N sec while agent still tool-using | `--watchdog-idle-work-timeout` (default 180s) |

Disable with `--no-watchdog` (for debugging the agent itself).

Killed runs land in `results.jsonl` as `status: failed` with
`reason: watchdog: <code> (<detail>)` — grep-friendly and
`--retry-failed` re-picks them.

### Flag gate (pre-commit)

Every flag candidate runs through `hydra/flag_gate.py` before being
written to `flags.json`:

- REJECT: unclosed brace, wrong prefix, format mismatch, length bounds,
  control chars, whitespace. `flags.json` stays clean; status = `failed`.
- WARN: missing scratch artifacts, or `prior-knowledge.log` present.
  Status = `solved_uncertain`; flag is recorded but flagged for human
  verification.
- ACCEPT: normal.

Tighten the gate per-challenge in your JSON:
```
{"name": "splash", "flag_prefix": "WANLAI",
 "expected_format": "WANLAI\\{[0-9a-f]{32}\\}"}
```
```

- [ ] **Step 2: Update `CLAUDE.md`'s "Hard stops" section**

Append these bullets to the existing list:
```markdown
- **Your container is supervised.** A deterministic watchdog on the host
  tails your `logs/claude.stdout.jsonl` and will kill this container if
  you: (a) run the same Bash prefix 3+ times, (b) write >5
  solveN/probeN/exploitN.py variants, (c) leave `work/` idle >3min while
  still tool-using, (d) exceed the cost cap, or (e) approach OOM.
  Diagnose the failure and change approach; don't just retry.
- **Flag candidates are gated.** A broken flag (unclosed brace, wrong
  prefix, missing scratch) won't reach `flags.json`. Write `./flag.txt`
  only when you've derived the complete flag. Partial progress belongs
  in `./work/`, not `./flag.txt`.
```

- [ ] **Step 3: Commit**

```
git add README.md CLAUDE.md
git commit -m "docs: document watchdog signals + flag-gate semantics"
```

---

## Final verification

- [ ] **Run the full suite + lint**

```
.venv/bin/pytest -v
.venv/bin/python -m ruff check .
```

Expected:
- Every test in `tests/unit/` + `tests/integration/` passes.
- ruff reports 0 warnings.

- [ ] **Grep for accidental placeholders**

```
grep -rnE 'TODO|FIXME|xxx placeholder' hydra/ tests/
```
Expected: no output (or only pre-existing comments unrelated to this plan).

- [ ] **Confirm commit history**

```
git log --oneline main..HEAD
```
Expected: 11–13 commits, all conventional-commit prefixed.

---

## Self-review notes

- **Spec coverage:** Part A (Gate) and Part B (Watchdog) are both covered task-by-task with tests before implementation. Integration smoke (B10) exercises both subsystems together.
- **No placeholders:** Every step contains the full code it references. One "docstring describes behavior" comment remains in `docker_mem_sampler`, but the logic is also there.
- **Type consistency:** `KillReason` is the single cross-module type — imported in `orchestrator.py` once. `Verdict` (flag_gate) vs. `Verdict` (flag_validator) are intentionally separate (gate is pre-commit, validator is post-hoc verifier routing); imported in orchestrator as `GateVerdictEnum` to keep them apart.
- **Tuple-shape change:** `_attempt` return changes from `(wd, wr)` to `(wd, wr, kill)`. Both call sites (`_one` and `_pass_at_k`) are updated in Task B8. No other call sites exist.
- **Status vocabulary:** Reuses existing `solved_uncertain` / `failed` — `Status` literal stays at 5 values.
- **Clock hygiene:** `work/` mtime is wall-clock (`st_mtime`), tool-use recency is monotonic (`time.monotonic()`). Comparison in `_check_idle_work` uses each clock for its own side.
- **Back-compat:** `--no-watchdog` + `watchdog_enabled=False` guarantees existing tests (and users who want bare-metal behaviour) see the old path. The flag gate is always on because it's pure — no external effects — but it only tightens REJECT rules on challenges that opt in via `expected_format`/`flag_prefix`.
