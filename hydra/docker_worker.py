import asyncio
import os
import re
import time
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


# Peak in-memory retention per stream. Flag extraction scans `stdout`
# from the WorkerResult, so we keep the tail — flags appear near the end
# of a transcript. Older bytes are safely on disk already. 128 MB tail
# handles multi-hour stream-json transcripts, and at --parallel 8 caps
# peak RAM at ~1 GB for stdout + ~128 MB for stderr instead of unbounded.
_DEFAULT_STDOUT_BUFFER = 128 * 1024 * 1024
_DEFAULT_STDERR_BUFFER = 16 * 1024 * 1024


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
    max_stdout_buffer: int = _DEFAULT_STDOUT_BUFFER,
    max_stderr_buffer: int = _DEFAULT_STDERR_BUFFER,
) -> WorkerResult:
    """Run one `claude -p` CTF-solve in a Docker container.

    Authentication (exactly one of):
      - credentials_dir: host dir with a logged-in Claude Code credentials
        file. Mounted at /root/.claude:ro inside the container so the
        containerized `claude` CLI uses the host's subscription auth.
      - api_key: ANTHROPIC_API_KEY, passed via `-e`.

    credentials_dir is preferred when both are supplied.

    Output is streamed to workdir/logs/ as the container writes it (so
    `tail -f` works during a live run) and only a bounded tail is kept
    in memory for flag extraction — caps peak RAM no matter how chatty
    the agent is.
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

    # Create logs dir upfront so streaming writes land somewhere real.
    logs_dir = workdir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = logs_dir / "claude.stdout.jsonl"
    stderr_path = logs_dir / "claude.stderr.log"

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_task = asyncio.create_task(
        _stream_to_file(proc.stdout, stdout_path, max_buffer=max_stdout_buffer)
    )
    stderr_task = asyncio.create_task(
        _stream_to_file(proc.stderr, stderr_path, max_buffer=max_stderr_buffer)
    )

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout_s)
    except TimeoutError:
        timed_out = True
        await _docker_stop(engine, container_name)
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=15)
        except TimeoutError:
            pass
    except asyncio.CancelledError:
        await _docker_stop(engine, container_name)
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=15)
        except TimeoutError:
            pass
        stdout_task.cancel()
        stderr_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise

    # Streams close when the child's pipes close; after proc exit/kill
    # that happens quickly.
    stream_results = await asyncio.gather(
        stdout_task, stderr_task, return_exceptions=True
    )
    stdout_bytes = stream_results[0] if isinstance(stream_results[0], bytes) else b""
    stderr_bytes = stream_results[1] if isinstance(stream_results[1], bytes) else b""

    duration = time.monotonic() - start
    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    return WorkerResult(
        name=name,
        exit_code=proc.returncode if proc.returncode is not None else -1,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_s=duration,
    )


async def _stream_to_file(
    stream,
    path: Path,
    *,
    max_buffer: int,
    chunk_size: int = 65536,
) -> bytes:
    """Drain an async pipe to `path` while keeping a bounded tail in RAM.

    The on-disk copy is complete and flushed after every chunk so
    `tail -f runs/<name>/logs/claude.stdout.jsonl` sees live output.
    The returned bytes hold at most `max_buffer` bytes of the *tail*,
    which is where flags live in practice.
    """
    if stream is None:
        return b""
    buf = bytearray()
    with path.open("wb") as f:
        while True:
            chunk = await stream.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            f.flush()
            buf.extend(chunk)
            if len(buf) > max_buffer:
                del buf[:-max_buffer]
    return bytes(buf)


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
