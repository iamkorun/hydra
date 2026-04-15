import asyncio
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENGINE = os.environ.get("HYDRA_CONTAINER_ENGINE", "docker")

# Docker container names must match [a-zA-Z0-9][a-zA-Z0-9_.-]*. Challenge
# names survive normalize.safe_name() but that preserves non-ASCII (unicode
# is valid on the filesystem), so we need a stricter pass for --name.
_DOCKER_NAME_SANITIZE = re.compile(r"[^a-zA-Z0-9_-]")


def _docker_safe_name(name: str, *, max_len: int = 32) -> str:
    cleaned = _DOCKER_NAME_SANITIZE.sub("_", name)[:max_len].lstrip("-._") or "x"
    return cleaned

_PROMPT = (
    "Solve the CTF challenge in this workspace. Read CLAUDE.md first, "
    "triage the category, dispatch to the appropriate specialist via the "
    "Task tool, recover the flag, write it to ./flag.txt, and echo "
    "`FLAG: <flag>` as the final line of your response."
)


@dataclass
class WorkerResult:
    name: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    duration_s: float


async def run_worker(
    *,
    name: str,
    workdir: Path,
    image: str,
    model: str,
    timeout_s: float,
    container_cpus: int,
    container_memory: str,
    prompt_volumes: dict[Path, str],
    api_key: str | None = None,
    credentials_dir: Path | None = None,
    engine: str = DEFAULT_ENGINE,
) -> WorkerResult:
    """Run one `claude -p` CTF-solve in a Docker container.

    Authentication (exactly one of):
      - credentials_dir: host dir with a logged-in Claude Code credentials
        file. Mounted at /root/.claude:ro inside the container so the
        containerized `claude` CLI uses the host's subscription auth.
      - api_key: ANTHROPIC_API_KEY, passed via `-e`.

    credentials_dir is preferred when both are supplied.
    """
    if credentials_dir is None and not api_key:
        raise ValueError(
            "run_worker requires either credentials_dir (preferred) or api_key"
        )

    container_name = f"hydra-{_docker_safe_name(name)}-{uuid.uuid4().hex[:8]}"

    cmd = [
        engine, "run", "--rm",
        "--name", container_name,
        "--network", "bridge",
        "--memory", container_memory,
        "--cpus", str(container_cpus),
        "-v", f"{workdir.resolve()}:/workspace",
    ]
    for src, dest in prompt_volumes.items():
        cmd += ["-v", f"{src.resolve()}:{dest}:ro"]
    if credentials_dir is not None:
        cmd += ["-v", f"{credentials_dir.resolve()}:/root/.claude:ro"]
    elif api_key:
        cmd += ["-e", f"ANTHROPIC_API_KEY={api_key}"]
    cmd += [
        "-w", "/workspace",
        image,
        "claude", "-p", _PROMPT,
        "--model", model,
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
    ]

    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_s
        )
    except TimeoutError:
        timed_out = True
        await _docker_stop(engine, container_name)
        proc.kill()
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=15
            )
        except TimeoutError:
            await proc.wait()
            stdout_bytes, stderr_bytes = b"", b""
    except asyncio.CancelledError:
        await _docker_stop(engine, container_name)
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=15)
        except TimeoutError:
            pass
        raise

    duration = asyncio.get_event_loop().time() - start
    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    (workdir / "logs").mkdir(parents=True, exist_ok=True)
    (workdir / "logs" / "claude.stdout.jsonl").write_text(stdout)
    (workdir / "logs" / "claude.stderr.log").write_text(stderr)

    return WorkerResult(
        name=name,
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_s=duration,
    )


async def _docker_stop(engine: str, container_name: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        engine, "stop", "--time", "10", container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=15)
    except TimeoutError:
        pass
