import asyncio
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from hydra.models import Challenge, Result
from hydra.workdir import build_workdir
from hydra.flag_extractor import extract_flag
from hydra.failures import write_failure_md, write_failures_summary
from hydra.docker_worker import (
    run_worker, WorkerResult, stop_container, _docker_safe_name,
)
from hydra.heartbeat import Heartbeat
from hydra.usage import parse_usage_dir
from hydra.remote_contact import was_remote_contacted
from hydra.flag_gate import Verdict as GateVerdictEnum, check as gate_check
from hydra.watchdog import (
    Watchdog, WatchdogConfig, KillReason, docker_mem_sampler,
)

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
    # Sidecar watchdog config. `None` disables the watchdog entirely
    # (tests and `--no-watchdog` use this path).
    watchdog: WatchdogConfig | None = field(default_factory=lambda: WatchdogConfig(
        cost_cap_usd=10.0,
        mem_kill_pct=90.0,
        max_same_bash_repeats=3,
        max_solver_variants=5,
        idle_work_timeout_s=180.0,
    ))

class Orchestrator:
    def __init__(
        self,
        cfg: OrchestratorConfig,
        *,
        writer,
        heartbeat: Heartbeat | None = None,
    ):
        self.cfg = cfg
        self.writer = writer
        self._hb = heartbeat
        self._sem: asyncio.Semaphore | None = None
        self._results: list[Result] = []

    async def run(self, challenges: list[Challenge]) -> None:
        self._sem = asyncio.Semaphore(self.cfg.parallel)
        work = [
            self._safe_one(c) for c in challenges if c.name not in self.cfg.skip_names
        ]
        try:
            # return_exceptions=True + _safe_one's own try/except is belt-
            # and-suspenders: a single flaky docker spawn or workdir perm
            # error must never cancel the rest of the batch.
            await asyncio.gather(*work, return_exceptions=True)
        finally:
            if self._results:
                write_failures_summary(
                    self._results, failures_dir=self.cfg.failures_dir
                )

    async def _safe_one(self, c: Challenge) -> None:
        """Run _one(c) and convert any unexpected exception into an error
        Result. CancelledError is re-raised so legitimate cancellation
        still propagates."""
        started = _now_iso()
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
                # Best-effort: don't let markdown-writing fail the Result
                # we already recorded.
                pass
            await self._emit_status(r)

    async def _one(self, c: Challenge, *, started: str | None = None) -> None:
        assert self._sem is not None
        if started is None:
            started = _now_iso()
        if self._hb is not None:
            # Track at the challenge-root workdir so pass@k heartbeats
            # aggregate all K attempts under one line.
            self._hb.track(c.name, self.cfg.runs_dir / c.name)
        try:
            if self.cfg.attempts <= 1:
                async with self._sem:
                    wd, wr, kill = await self._attempt(c, subpath=None)
            else:
                wd, wr, kill = await self._pass_at_k(c)
        finally:
            if self._hb is not None:
                self._hb.untrack(c.name)

        flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

        if kill is not None:
            # Watchdog wins over everything else — even if flag.txt holds a
            # candidate, a tripped watchdog means the run wasn't healthy.
            flag = None
            status, reason = "failed", str(kill)
        elif wr.timed_out:
            status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
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
        elif wr.exit_code != 0:
            status = "error"
            reason = (wr.stderr[-1024:] if wr.stderr else f"worker exited {wr.exit_code}")
        else:
            status, reason = "failed", "no flag recovered from stdout or flag.txt"

        # Parse usage from the challenge root so pass@k sums all attempts,
        # not just the winner's subdir.
        usage = parse_usage_dir(self.cfg.runs_dir / c.name)
        r = Result(
            name=c.name, status=status, flag=flag,
            duration_s=wr.duration_s,
            started_at=started, finished_at=_now_iso(),
            worker_exit_code=wr.exit_code,
            work_dir=str(wd),
            reason=reason,
            usage=usage,
        )
        self._results.append(r)
        self.writer.append(r)
        if status != "solved":
            write_failure_md(c, r, work_dir=wd, failures_dir=self.cfg.failures_dir)
        await self._emit_status(r)

    async def _emit_status(self, r: Result) -> None:
        """Route the per-challenge completion line through the heartbeat
        (if active) so it lands above the live region without collision."""
        line = _status_line(r)
        if self._hb is not None:
            await self._hb.print_permanent(line)
        else:
            print(line, flush=True)

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
        if self.cfg.watchdog is None:
            try:
                wr = await worker_task
            except asyncio.CancelledError:
                worker_task.cancel()
                await asyncio.gather(worker_task, return_exceptions=True)
                raise
            return wd, wr, None

        jsonl = wd / "logs" / "claude.stdout.jsonl"
        watchdog = Watchdog(
            container_name=container_name,
            jsonl_path=jsonl,
            work_dir=wd / "work",
            config=self.cfg.watchdog,
            mem_sampler=docker_mem_sampler(),
            model_name=self.cfg.model,
        )
        wd_task = asyncio.create_task(watchdog.run())

        try:
            done, _pending = await asyncio.wait(
                [worker_task, wd_task], return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            # Parent cancellation (e.g. pass@k winner cancels siblings):
            # tear down both child tasks before propagating.
            for t in (worker_task, wd_task):
                t.cancel()
            await asyncio.gather(worker_task, wd_task, return_exceptions=True)
            raise
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
        winner: tuple[Path, WorkerResult, str] | None = None  # wd, wr, flag
        last: tuple[Path, WorkerResult, KillReason | None] | None = None

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    try:
                        wd, wr, kill = t.result()
                    except asyncio.CancelledError:
                        continue
                    last = (wd, wr, kill)
                    flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)
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
            # Publish the winning flag to the canonical top-level path so
            # external tooling sees a single source of truth. The winner
            # may have produced the flag via stdout only (empty flag.txt),
            # so write the extracted flag string rather than copying the file.
            top_flag = self.cfg.runs_dir / c.name / "flag.txt"
            top_flag.write_text(winner[2] + "\n")
            return winner[0], winner[1], None
        assert last is not None, "all pass@k attempts cancelled without completing"
        return last

def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

def _status_line(r: Result) -> str:
    sym = "✓" if r.status == "solved" else "✗"
    detail = r.flag if r.status == "solved" else f"({r.reason or r.status})"
    cost = f", ${r.usage.cost_usd:.2f}" if r.usage.cost_usd else ""
    return f"{sym} {r.name:24s} → {detail} ({r.duration_s:.1f}s{cost})"
