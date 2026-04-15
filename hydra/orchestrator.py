import asyncio
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from hydra.models import Challenge, Result
from hydra.workdir import build_workdir
from hydra.flag_extractor import extract_flag
from hydra.failures import write_failure_md, write_failures_summary
from hydra.docker_worker import run_worker, WorkerResult

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

class Orchestrator:
    def __init__(self, cfg: OrchestratorConfig, *, writer):
        self.cfg = cfg
        self.writer = writer
        self._sem: asyncio.Semaphore | None = None
        self._results: list[Result] = []

    async def run(self, challenges: list[Challenge]) -> None:
        self._sem = asyncio.Semaphore(self.cfg.parallel)
        work = [
            self._one(c) for c in challenges if c.name not in self.cfg.skip_names
        ]
        try:
            await asyncio.gather(*work)
        finally:
            if self._results:
                write_failures_summary(
                    self._results, failures_dir=self.cfg.failures_dir
                )

    async def _one(self, c: Challenge) -> None:
        assert self._sem is not None
        started = _now_iso()
        if self.cfg.attempts <= 1:
            async with self._sem:
                wd, wr = await self._attempt(c, subpath=None)
        else:
            wd, wr = await self._pass_at_k(c)

        flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

        if wr.timed_out:
            status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
        elif flag:
            status, reason = "solved", None
        elif wr.exit_code != 0:
            status = "error"
            reason = (wr.stderr[-1024:] if wr.stderr else f"worker exited {wr.exit_code}")
        else:
            status, reason = "failed", "no flag recovered from stdout or flag.txt"

        r = Result(
            name=c.name, status=status, flag=flag,
            duration_s=wr.duration_s,
            started_at=started, finished_at=_now_iso(),
            worker_exit_code=wr.exit_code,
            work_dir=str(wd),
            reason=reason,
        )
        self._results.append(r)
        self.writer.append(r)
        if status != "solved":
            write_failure_md(c, r, work_dir=wd, failures_dir=self.cfg.failures_dir)
        _print_status(r)

    async def _attempt(
        self, c: Challenge, *, subpath: str | None
    ) -> tuple[Path, WorkerResult]:
        """Run a single solve attempt, returning (workdir, worker_result)."""
        wd = build_workdir(c, runs_dir=self.cfg.runs_dir, subpath=subpath)
        wr = await run_worker(
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
        )
        return wd, wr

    async def _pass_at_k(self, c: Challenge) -> tuple[Path, WorkerResult]:
        """Fan out N attempts. First one to produce a flag wins; cancel the rest.
        Each attempt consumes a semaphore slot, so N parallel attempts reduce
        the effective cross-challenge concurrency by N."""
        assert self._sem is not None
        k = self.cfg.attempts

        async def one_slotted(idx: int) -> tuple[Path, WorkerResult]:
            async with self._sem:
                return await self._attempt(c, subpath=f"a{idx + 1}")

        tasks = [asyncio.create_task(one_slotted(i)) for i in range(k)]
        pending = set(tasks)
        winner: tuple[Path, WorkerResult, str] | None = None  # wd, wr, flag
        last: tuple[Path, WorkerResult] | None = None

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for t in done:
                    try:
                        wd, wr = t.result()
                    except asyncio.CancelledError:
                        continue
                    last = (wd, wr)
                    flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)
                    if flag and not wr.timed_out:
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
            return winner[0], winner[1]
        assert last is not None, "all pass@k attempts cancelled without completing"
        return last

def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

def _print_status(r: Result) -> None:
    sym = "✓" if r.status == "solved" else "✗"
    detail = r.flag if r.status == "solved" else f"({r.reason or r.status})"
    print(f"{sym} {r.name:24s} → {detail} ({r.duration_s:.1f}s)", flush=True)
