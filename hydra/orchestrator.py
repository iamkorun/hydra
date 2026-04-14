import asyncio
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    api_key: str
    runs_dir: Path
    failures_dir: Path
    prompt_volumes: dict[Path, str]
    container_cpus: int = 2
    container_memory: str = "8g"
    skip_names: set[str] = field(default_factory=set)

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
        async with self._sem:
            started = _now_iso()
            wd = build_workdir(c, runs_dir=self.cfg.runs_dir)
            wr: WorkerResult = await run_worker(
                name=c.name,
                workdir=wd,
                image=self.cfg.image,
                api_key=self.cfg.api_key,
                model=self.cfg.model,
                timeout_s=self.cfg.timeout_s,
                container_cpus=self.cfg.container_cpus,
                container_memory=self.cfg.container_memory,
                prompt_volumes=self.cfg.prompt_volumes,
            )
            flag = extract_flag(flag_file=wd / "flag.txt", stdout=wr.stdout)

            if wr.timed_out:
                status, reason = "timeout", f"wall-clock timeout after {self.cfg.timeout_s}s"
            elif flag:
                status, reason = "solved", None
            else:
                status, reason = "failed", (
                    wr.stderr[-1024:] if wr.exit_code != 0 and wr.stderr
                    else "no flag recovered from stdout or flag.txt"
                )

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

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

def _print_status(r: Result) -> None:
    sym = "✓" if r.status == "solved" else "✗"
    detail = r.flag if r.status == "solved" else f"({r.reason or r.status})"
    print(f"{sym} {r.name:24s} → {detail} ({r.duration_s:.1f}s)", flush=True)
