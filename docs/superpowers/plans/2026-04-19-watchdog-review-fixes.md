# Watchdog + Flag Gate — Review Fix-ups

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 5 MEDIUM-or-higher issues found in the `d422c27..db245a5` code review before the feature ships against live batches.

**Issues addressed:**

| # | Sev | Summary |
|---|---|---|
| 1 | 🔴 CRITICAL | Container-name mismatch between `_attempt` and `run_worker` makes `oom_preempt` + watchdog-stop dead code in production |
| 2 | 🟡 HIGH | `docker_mem_sampler` has no unit test |
| 3 | 🟡 HIGH | `OrchestratorConfig` has 6 redundant watchdog_* fields; should be one `WatchdogConfig | None` |
| 4 | 🟡 MEDIUM | `_one` reason-clobbers on multi-signal demotion (OOM eats gate-WARN info) |
| 5 | 🟡 MEDIUM | `--watchdog-max-solver-variants` help text says "more than N" but code fires at `>= N` |

**Architecture:** Purely incremental. `run_worker` gains an optional `container_name` kwarg; `_attempt` generates the canonical name and feeds it to both `run_worker` and `Watchdog`, guaranteeing `docker stats` / `docker stop` hit the real container. Config surface shrinks: six watchdog fields on `OrchestratorConfig` collapse to a single `WatchdogConfig | None`. Reason assembly in `_one` switches from first-match to accumulator so operators see every soft-demotion signal. No new modules, no new deps.

**Tech Stack:** Same as base feature.

**Execution order:** Sequential. Task 5 (config collapse) touches fields Tasks 1+3 modify; doing it last keeps each smaller change in a single-purpose diff.

---

## File Structure

**Modify:**
- `hydra/docker_worker.py:49-95` — add optional `container_name` param to `run_worker`
- `hydra/orchestrator.py:10, 189-269` — generate name in `_attempt`, pass to both tasks
- `hydra/orchestrator.py:115-154` — accumulate `solved_uncertain` reasons (Task 3)
- `hydra/orchestrator.py:16-41` — config collapse (Task 5)
- `hydra/cli.py` — help text fix (Task 4); config collapse (Task 5)
- `hydra/watchdog.py:280` — hoist `subprocess` import to module top (Task 2)
- `tests/unit/test_docker_worker.py` — `container_name` signature test
- `tests/unit/test_watchdog.py` — `docker_mem_sampler` unit tests
- `tests/unit/test_orchestrator.py` — orchestrator-level name-round-trip test; reason-accumulation test; config-shape test
- `tests/unit/test_cli.py` — adjust tests after config collapse

---

## Task 1: Thread `container_name` through `run_worker` (CRITICAL)

**Files:**
- `hydra/docker_worker.py`
- `hydra/orchestrator.py`
- `tests/unit/test_docker_worker.py` (signature test)
- `tests/unit/test_orchestrator.py` (round-trip test)

- [ ] **Step 1: Write a signature test at the docker_worker layer**

Add to `tests/unit/test_docker_worker.py`:
```python
def test_run_worker_signature_accepts_container_name():
    """Regression: orchestrator must be able to hand run_worker a shared
    container_name so the sidecar Watchdog targets the real container."""
    import inspect
    from hydra.docker_worker import run_worker

    sig = inspect.signature(run_worker)
    assert "container_name" in sig.parameters
    # Default must be None so existing callers (and tests) keep working.
    assert sig.parameters["container_name"].default is None
```

- [ ] **Step 2: Write the orchestrator-level round-trip test**

Add to `tests/unit/test_orchestrator.py`:
```python
async def test_attempt_shares_container_name_between_worker_and_watchdog(
    tmp_path, monkeypatch
):
    """Regression for a bug where _attempt used `f"hydra-{c.name}"` while
    run_worker generated `f"hydra-<safe>-<uuid>"`. The Watchdog's
    mem_sampler and the orchestrator's stop_container both take the
    prefix-form → neither would ever match the actual container in prod.

    After the fix, _attempt generates the canonical name ONCE and hands
    the same string to both run_worker and Watchdog.
    """
    from hydra.watchdog import KillReason, WatchdogConfig

    captured_worker: dict = {}
    captured_wd: list[str] = []
    captured_stop: list[str] = []

    async def fake_run_worker(**kwargs):
        captured_worker.update(kwargs)
        # Simulate a slow worker so the watchdog wins the race.
        await asyncio.sleep(0.5)
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout="", stderr="", timed_out=False, duration_s=0.5,
        )

    class RecordingInstantKillWatchdog:
        def __init__(self, *, container_name, **kw):
            captured_wd.append(container_name)
        async def run(self) -> KillReason:
            return KillReason(code="bash_repeat", detail="test-triggered")

    async def capturing_stop(engine, name):
        captured_stop.append(name)

    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_run_worker)
    monkeypatch.setattr("hydra.orchestrator.Watchdog", RecordingInstantKillWatchdog)
    monkeypatch.setattr("hydra.orchestrator.stop_container", capturing_stop)

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
    await orch.run([Challenge(name="Chal-1", description="x")])

    # 1. run_worker received a container_name kwarg at all.
    assert "container_name" in captured_worker
    shared = captured_worker["container_name"]
    # 2. Name has the canonical docker-safe shape.
    assert shared.startswith("hydra-Chal-1-")
    assert len(shared) > len("hydra-Chal-1-")  # has uuid suffix
    # 3. Watchdog was given the SAME name.
    assert captured_wd == [shared]
    # 4. stop_container was called with the SAME name.
    assert captured_stop == [shared]
```

- [ ] **Step 3: Run — both fail**

```
.venv/bin/pytest tests/unit/test_docker_worker.py::test_run_worker_signature_accepts_container_name tests/unit/test_orchestrator.py::test_attempt_shares_container_name_between_worker_and_watchdog -v
```
Expected:
- signature test fails: `container_name` not in params
- round-trip test fails: either `run_worker` rejects the kwarg, or the name the orchestrator sends ≠ what Watchdog / stop_container see

- [ ] **Step 4: Add the parameter to `run_worker`**

Edit `hydra/docker_worker.py`. In the `run_worker` keyword-only signature block (around line 62), add:
```python
    container_name: str | None = None,
```

Replace line 85:
```python
    container_name = container_name or f"hydra-{_docker_safe_name(name)}-{uuid.uuid4().hex[:8]}"
```

Update the docstring (around line 79) so the contract is clear:
```
    container_name: override the auto-generated `hydra-<safe>-<uuid>`
        name. Orchestrator uses this so the sidecar Watchdog can target
        the exact same container for `docker stats` / `docker stop`.
```

- [ ] **Step 5: Wire the shared name in `_attempt`**

Edit `hydra/orchestrator.py`. Update the import on line 10:
```python
from hydra.docker_worker import (
    run_worker, WorkerResult, stop_container, _docker_safe_name,
)
```

Add `import uuid` to the top-of-file imports if not already present (it isn't — `hydra/docker_worker.py` has it but orchestrator doesn't).

Rewrite the top of `_attempt` (around line 189-207). Replace the signature docstring and the worker-task spawn with:

```python
    async def _attempt(
        self, c: Challenge, *, subpath: str | None
    ) -> tuple[Path, WorkerResult, KillReason | None]:
        """Run one solve attempt alongside a Watchdog. Returns
        (workdir, worker_result, kill_reason_or_None).

        The container_name is generated HERE (not inside run_worker) so
        the Watchdog targets the exact same name for `docker stats` and
        `docker stop`. Before this, _attempt used `f"hydra-{c.name}"` but
        run_worker generated `f"hydra-<safe>-<uuid>"` — the mismatch made
        oom_preempt and watchdog-initiated stops dead code in production.
        """
        wd = build_workdir(c, runs_dir=self.cfg.runs_dir, subpath=subpath)
        container_name = (
            f"hydra-{_docker_safe_name(c.name)}-{uuid.uuid4().hex[:8]}"
        )

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
            container_name=container_name,
        ))
```

The rest of `_attempt` already references `container_name` correctly — no further edit needed.

- [ ] **Step 6: Run both tests + full suite**

```
.venv/bin/pytest tests/unit/test_docker_worker.py tests/unit/test_orchestrator.py -v
.venv/bin/pytest
```
Expected: 195+ passing overall (193 baseline + 2 new).

- [ ] **Step 7: Commit**

```
git add hydra/docker_worker.py hydra/orchestrator.py tests/unit/test_docker_worker.py tests/unit/test_orchestrator.py
git commit -m "fix(orchestrator,docker_worker): share container_name so watchdog can stat/stop the real container"
```

---

## Task 2: `docker_mem_sampler` unit tests (HIGH)

**Files:**
- `hydra/watchdog.py` (hoist `subprocess` import)
- `tests/unit/test_watchdog.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/unit/test_watchdog.py`:
```python
def test_docker_mem_sampler_parses_percent(monkeypatch):
    """Happy path: `docker stats` prints '12.34%\n'; sampler returns 12.34."""
    from hydra.watchdog import docker_mem_sampler

    class _Out:
        returncode = 0
        stdout = "12.34%\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Out())
    assert docker_mem_sampler()("hydra-chal-deadbeef") == 12.34


def test_docker_mem_sampler_returns_none_on_missing_container(monkeypatch):
    """Container gone → non-zero rc. Returns None (not 0.0) so the
    watchdog does not mistake 'unavailable' for 'no pressure'."""
    from hydra.watchdog import docker_mem_sampler

    class _Out:
        returncode = 1
        stdout = ""

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Out())
    assert docker_mem_sampler()("hydra-gone") is None


def test_docker_mem_sampler_returns_none_on_timeout(monkeypatch):
    """docker daemon hang → subprocess timeout → None."""
    import subprocess as _sp
    from hydra.watchdog import docker_mem_sampler

    def _boom(*a, **kw):
        raise _sp.TimeoutExpired(cmd="docker", timeout=5)

    monkeypatch.setattr("subprocess.run", _boom)
    assert docker_mem_sampler()("hydra-slow") is None


def test_docker_mem_sampler_returns_none_on_unparseable(monkeypatch):
    """Some stats output forms (e.g. '--') aren't floats. Return None."""
    from hydra.watchdog import docker_mem_sampler

    class _Out:
        returncode = 0
        stdout = "--\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Out())
    assert docker_mem_sampler()("hydra-new") is None
```

- [ ] **Step 2: Run — expect that monkeypatch hits the wrong symbol**

```
.venv/bin/pytest tests/unit/test_watchdog.py::test_docker_mem_sampler_parses_percent -v
```

If the test hangs or actually invokes `docker stats`, it's because the factory body imports `subprocess` locally — `monkeypatch.setattr("subprocess.run", ...)` patches the top-level module, but the factory's inner binding still points at the pre-patch version on first call. Moving the import to module-top fixes this and is also the LOW nit from the review.

- [ ] **Step 3: Hoist `subprocess` to module-top**

Edit `hydra/watchdog.py`. Add to the imports block (around line 15-22, near `import json`):
```python
import subprocess
```

Remove the `import subprocess` line from inside `docker_mem_sampler`.

- [ ] **Step 4: Re-run the tests**

```
.venv/bin/pytest tests/unit/test_watchdog.py -v
```
Expected: all PASS (existing 8 + 4 new = 12).

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest
```
Expected: 199 passing (195 after Task 1 + 4 new).

- [ ] **Step 6: Commit**

```
git add hydra/watchdog.py tests/unit/test_watchdog.py
git commit -m "test(watchdog): docker_mem_sampler unit coverage + hoist subprocess import"
```

---

## Task 3: Accumulate `solved_uncertain` reasons (MEDIUM)

**Files:**
- `hydra/orchestrator.py:115-154`
- `tests/unit/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_orchestrator.py`:
```python
async def test_multiple_soft_demotions_accumulate_reasons(tmp_path, monkeypatch):
    """Exit 137 + gate WARN (no_scratch) both demote to solved_uncertain.
    Reason must mention both signals so humans can verify correctly,
    not get only the first-match string."""
    async def worker_oom_no_scratch(*args, **kwargs):
        wd = kwargs["workdir"]
        wd.mkdir(parents=True, exist_ok=True)
        (wd / "flag.txt").write_text("HTB{body}\n")
        # no work/ dir → no_scratch WARN
        return WorkerResult(
            name=kwargs["name"], exit_code=137,
            stdout="", stderr="", timed_out=False, duration_s=0.1,
        )

    monkeypatch.setattr("hydra.orchestrator.run_worker", worker_oom_no_scratch)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        watchdog_enabled=False,
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x", flag_prefix="HTB")])
    [r] = writer.appended
    assert r.status == "solved_uncertain"
    assert "OOM" in (r.reason or "") or "137" in (r.reason or "")
    assert "no_scratch" in (r.reason or "")
```

- [ ] **Step 2: Run — fails**

```
.venv/bin/pytest tests/unit/test_orchestrator.py::test_multiple_soft_demotions_accumulate_reasons -v
```
Expected: FAIL — reason is only the OOM string, `no_scratch` missing.

- [ ] **Step 3: Rewrite the flag-extracted branch in `_one`**

Edit `hydra/orchestrator.py`. Replace the entire `elif flag:` block (currently around lines 117-154) with:

```python
        elif flag:
            gate = gate_check(flag, c, wd)
            log_file = wd / "logs" / "claude.stdout.jsonl"

            # REJECT is terminal — flag never reaches flags.json.
            if gate.verdict == GateVerdictEnum.REJECT:
                flag = None
                status, reason = "failed", f"flag_gate rejected: {gate.reason}"
            else:
                # Collect every soft-demotion signal so Result.reason
                # shows all of them, not just the first match.
                soft: list[str] = []
                if wr.exit_code == 137:
                    soft.append(
                        "worker exited 137 (SIGKILL / OOM) — flag may be stale"
                    )
                if c.remote and not was_remote_contacted(log_file, c.remote):
                    soft.append(
                        f"no evidence agent contacted remote {c.remote} — "
                        "likely false positive from README/binary string"
                    )
                if gate.verdict == GateVerdictEnum.WARN:
                    soft.append(f"flag_gate warn: {gate.reason}")

                if soft:
                    status, reason = "solved_uncertain", "; ".join(soft)
                else:
                    status, reason = "solved", None
```

- [ ] **Step 4: Run and check for collateral damage**

```
.venv/bin/pytest tests/unit/test_orchestrator.py -v
```

Expect the new test to PASS. Any failing pre-existing test whose assertion was looking for an exact old reason string needs a tweak — loosen to substring matches:

- `test_exit_137_with_flag_is_solved_uncertain` — already asserts `"OOM" in reason or "137" in reason`, still fine.
- `test_gate_warn_demotes_to_solved_uncertain` — asserts `"no_scratch" in r.reason`, still fine (accumulator produces `"flag_gate warn: no_scratch: ..."` which contains `"no_scratch"`).

If anything breaks, adjust with substring assertions, NOT by reverting the logic.

- [ ] **Step 5: Full suite**

```
.venv/bin/pytest
```
Expected: 200 passing (199 + 1 new).

- [ ] **Step 6: Commit**

```
git add hydra/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "fix(orchestrator): accumulate all soft-demotion signals into Result.reason"
```

---

## Task 4: Fix `--watchdog-max-solver-variants` help text (MEDIUM nit)

**Files:**
- `hydra/cli.py`

- [ ] **Step 1: Fix the wording**

Edit `hydra/cli.py`. Find the `--watchdog-max-solver-variants` argparse block and change:

```python
    p.add_argument(
        "--watchdog-max-solver-variants", type=int, default=5, metavar="N",
        help="Kill when the agent writes more than N files matching "
             "/workspace/work/{solve,probe,exploit}NNN.py.",
    )
```

to:

```python
    p.add_argument(
        "--watchdog-max-solver-variants", type=int, default=5, metavar="N",
        help="Kill when the agent writes N or more files matching "
             "/workspace/work/{solve,probe,exploit}NNN.py (default 5).",
    )
```

Align `--watchdog-max-bash-repeats` while you're here:

```python
    p.add_argument(
        "--watchdog-max-bash-repeats", type=int, default=3, metavar="N",
        help="Kill when the same Bash command prefix fires N or more "
             "times (default 3).",
    )
```

- [ ] **Step 2: Run CLI tests**

```
.venv/bin/pytest tests/unit/test_cli.py -v
```
Expected: all PASS (help text isn't asserted).

- [ ] **Step 3: Commit**

```
git add hydra/cli.py
git commit -m "docs(cli): align watchdog help text with actual >=N semantics"
```

---

## Task 5: Collapse `OrchestratorConfig` watchdog fields → single `WatchdogConfig | None` (HIGH)

Goes last because it touches fields Tasks 1 and 3 modify; doing it last means one clean refactor on top of a stable state.

**Files:**
- `hydra/orchestrator.py:16-41, ~218-232`
- `hydra/cli.py:19-48, 95-141, 285-308`
- `tests/unit/test_orchestrator.py`
- `tests/unit/test_cli.py`

- [ ] **Step 1: Smoke test for the new shape**

Append to `tests/unit/test_orchestrator.py`:
```python
def test_orchestrator_config_accepts_watchdog_object():
    """Collapsed config: `watchdog` is the sole knob; `None` disables."""
    from pathlib import Path as _P
    from hydra.watchdog import WatchdogConfig
    cfg_on = OrchestratorConfig(
        parallel=1, timeout_s=10, model="m",
        image="i", api_key="sk",
        runs_dir=_P("/tmp"), failures_dir=_P("/tmp"),
        prompt_volumes={},
        watchdog=WatchdogConfig(
            cost_cap_usd=5.0, mem_kill_pct=90.0,
            max_same_bash_repeats=3, max_solver_variants=5,
            idle_work_timeout_s=180.0,
        ),
    )
    assert cfg_on.watchdog is not None
    assert cfg_on.watchdog.cost_cap_usd == 5.0

    cfg_off = OrchestratorConfig(
        parallel=1, timeout_s=10, model="m",
        image="i", api_key="sk",
        runs_dir=_P("/tmp"), failures_dir=_P("/tmp"),
        prompt_volumes={},
        watchdog=None,
    )
    assert cfg_off.watchdog is None
```

- [ ] **Step 2: Run — fails**

```
.venv/bin/pytest tests/unit/test_orchestrator.py::test_orchestrator_config_accepts_watchdog_object -v
```
Expected: `TypeError: OrchestratorConfig got an unexpected keyword argument 'watchdog'`.

- [ ] **Step 3: Refactor `OrchestratorConfig`**

Edit `hydra/orchestrator.py:16-41`. Replace the dataclass:

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
    attempts: int = 1  # pass@k
    # Sidecar watchdog config. `None` disables the watchdog entirely
    # (tests and `--no-watchdog` use this path).
    watchdog: WatchdogConfig | None = field(default_factory=lambda: WatchdogConfig(
        cost_cap_usd=10.0,
        mem_kill_pct=90.0,
        max_same_bash_repeats=3,
        max_solver_variants=5,
        idle_work_timeout_s=180.0,
    ))
```

Update `_attempt`. Replace `if not self.cfg.watchdog_enabled:` with:
```python
        if self.cfg.watchdog is None:
            try:
                wr = await worker_task
            except asyncio.CancelledError:
                worker_task.cancel()
                await asyncio.gather(worker_task, return_exceptions=True)
                raise
            return wd, wr, None
```

Replace the Watchdog construction block with:
```python
        watchdog = Watchdog(
            container_name=container_name,
            jsonl_path=jsonl,
            work_dir=wd / "work",
            config=self.cfg.watchdog,
            mem_sampler=docker_mem_sampler(),
            model_name=self.cfg.model,
        )
```

- [ ] **Step 4: Refactor `ResolvedConfig` in `hydra/cli.py`**

Replace the six watchdog fields (around lines 37-46) with:
```python
    watchdog: WatchdogConfig | None = None
```

Add at the top of the file:
```python
from hydra.watchdog import WatchdogConfig
```

In `resolve_config`, replace the six `watchdog_*` assignments in the returned `ResolvedConfig` with:
```python
        watchdog=None if ns.no_watchdog else WatchdogConfig(
            cost_cap_usd=ns.watchdog_cost_cap,
            mem_kill_pct=ns.watchdog_mem_kill_pct,
            max_same_bash_repeats=ns.watchdog_max_bash_repeats,
            max_solver_variants=ns.watchdog_max_solver_variants,
            idle_work_timeout_s=ns.watchdog_idle_work_timeout,
        ),
```

In `_run`'s `OrchestratorConfig(...)` construction, drop the six `watchdog_*` fields and replace with:
```python
        watchdog=cfg.watchdog,
```

- [ ] **Step 5: Update tests**

`tests/unit/test_cli.py::test_resolve_config_plumbs_watchdog_to_config` — rewrite assertions:
```python
    assert cfg.watchdog is not None
    assert cfg.watchdog.cost_cap_usd == 2.0
    assert cfg.watchdog.mem_kill_pct == 80.5
    assert cfg.watchdog.max_same_bash_repeats == 5
    assert cfg.watchdog.max_solver_variants == 8
    assert cfg.watchdog.idle_work_timeout_s == 300.0
```

Add a disable test:
```python
def test_resolve_config_no_watchdog_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    from hydra.cli import build_parser, resolve_config
    ns = build_parser().parse_args([
        "chal.json", "--use-api-key", "--no-watchdog",
    ])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.watchdog is None
```

`tests/unit/test_orchestrator.py` — every `OrchestratorConfig(...)` that doesn't care about the watchdog should pass `watchdog=None,` so the default `WatchdogConfig` doesn't accidentally fire `docker_mem_sampler()` (which shells out). Grep and add:
```
grep -n 'OrchestratorConfig(' tests/unit/test_orchestrator.py
```

For every match where the test previously passed `watchdog_enabled=False` or doesn't exercise watchdog behavior, drop `watchdog_enabled` (removed) and add `watchdog=None,`.

For tests that exercise watchdog behavior (only `test_watchdog_kill_overrides_worker_result` and the Task-1 round-trip test), pass an explicit config:
```python
from hydra.watchdog import WatchdogConfig
...
cfg = OrchestratorConfig(
    ...,
    watchdog=WatchdogConfig(
        cost_cap_usd=10.0, mem_kill_pct=90.0,
        max_same_bash_repeats=3, max_solver_variants=5,
        idle_work_timeout_s=180.0,
    ),
)
```

Also update the `watchdog_enabled=True` usage in `test_watchdog_kill_overrides_worker_result` and `test_attempt_shares_container_name_between_worker_and_watchdog` to an explicit `WatchdogConfig`.

- [ ] **Step 6: Full suite**

```
.venv/bin/pytest
```
Expected: 201+ passing (200 + 1 new smoke + 1 new disable test). Fix any stragglers by auditing every OrchestratorConfig construction.

- [ ] **Step 7: Ruff**

```
.venv/bin/python -m ruff check .
```
Expected: zero findings.

- [ ] **Step 8: Commit**

```
git add hydra/orchestrator.py hydra/cli.py tests/unit/test_orchestrator.py tests/unit/test_cli.py
git commit -m "refactor(config): collapse OrchestratorConfig.watchdog_* into a single WatchdogConfig | None"
```

---

## Final verification

- [ ] **Full suite + ruff**

```
.venv/bin/pytest -v
.venv/bin/python -m ruff check .
```
Expected: all green, zero findings.

- [ ] **Regression grep — the bad pattern must be gone**

```
grep -rn 'f"hydra-{c.name}"' hydra/ tests/
```
Expected: no output.

- [ ] **Commit count**

```
git log --oneline db245a5..HEAD | wc -l
```
Expected: 5.

---

## Self-review notes

- **Spec coverage:** every issue ≥ MEDIUM from the review has a task. CRITICAL → Task 1; HIGH (test coverage) → Task 2; MEDIUM (reason-clobber) → Task 3; MEDIUM (help wording) → Task 4; HIGH (config shape) → Task 5.
- **No placeholders:** each step ships the literal code/diff.
- **Type consistency:** `WatchdogConfig` becomes the single source of truth after Task 5. `OrchestratorConfig.watchdog: WatchdogConfig | None` aligns with `ResolvedConfig.watchdog: WatchdogConfig | None`.
- **Refactor blast radius is bounded:** Task 5's `grep 'OrchestratorConfig('` step makes the test sweep mechanical.
- **Back-compat:** CLI flags are unchanged; only internal config shape changes. External users see no difference in behaviour or invocation.
- **Name-match regression:** Task 1 Step 2's round-trip test asserts `captured_wd[0] == captured_stop[0] == captured_worker["container_name"]` — would have caught the original bug. Locked in.
