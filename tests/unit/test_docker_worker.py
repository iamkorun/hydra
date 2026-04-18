import asyncio
from pathlib import Path
import pytest
from hydra.docker_worker import run_worker, WorkerResult

class FakeStreamReader:
    """Minimal asyncio.StreamReader stand-in: returns chunks up to n bytes
    until drained, then returns b'' (EOF). close() force-drains so a killed
    proc's streams report EOF immediately."""
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0
        self._closed = False

    async def read(self, n: int) -> bytes:
        if self._closed or self._pos >= len(self._data):
            return b""
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self) -> None:
        self._closed = True


class FakeProc:
    def __init__(self, *, returncode=0, stdout=b"FLAG: flag{x}\n", stderr=b"", delay=0.01):
        self.returncode = returncode
        self.stdout = FakeStreamReader(stdout)
        self.stderr = FakeStreamReader(stderr)
        self._delay = delay
        self._killed = False

    async def communicate(self):
        # Legacy API; not exercised by the streaming code path but kept
        # so tests that still reference it compile.
        await asyncio.sleep(self._delay)
        if self._killed:
            self.returncode = -9
        data_out = b""
        data_err = b""
        while True:
            c = await self.stdout.read(65536)
            if not c:
                break
            data_out += c
        while True:
            c = await self.stderr.read(65536)
            if not c:
                break
            data_err += c
        return data_out, data_err

    def kill(self):
        self._killed = True
        self.returncode = -9
        self.stdout.close()
        self.stderr.close()

    async def wait(self):
        if not self._killed:
            await asyncio.sleep(self._delay)
        return self.returncode

@pytest.fixture
def patch_subprocess(monkeypatch):
    captured_cmd = {}
    async def fake_create(*args, **kwargs):
        captured_cmd["cmd"] = args
        captured_cmd["kwargs"] = kwargs
        return captured_cmd.get("proc") or FakeProc()
    monkeypatch.setattr(
        "hydra.docker_worker.asyncio.create_subprocess_exec", fake_create
    )
    return captured_cmd

async def test_basic_run(tmp_path, patch_subprocess):
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    result: WorkerResult = await run_worker(
        name="x",
        workdir=wd,
        image="hydra-worker",
        api_key="sk-test",
        model="claude-opus-4-7",
        timeout_s=30,
        container_cpus=2,
        container_memory="4g",
        prompt_volumes={
            Path("/host/CLAUDE.md"): "/workspace/CLAUDE.md",
        },
    )
    assert result.exit_code == 0
    assert "flag{x}" in result.stdout

async def test_timeout_kills_container(tmp_path, monkeypatch):
    slow_proc = FakeProc(delay=5)
    captured = {}
    captured["proc"] = slow_proc

    async def fake_create(*args, **kwargs):
        return slow_proc
    monkeypatch.setattr(
        "hydra.docker_worker.asyncio.create_subprocess_exec", fake_create
    )

    # Stub `docker stop` helper to just mark kill.
    async def fake_stop(*a, **kw): return None
    monkeypatch.setattr("hydra.docker_worker.stop_container", fake_stop)

    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)

    result = await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=0.1,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )
    assert result.timed_out is True
    assert result.exit_code != 0

async def test_writes_logs(tmp_path, patch_subprocess):
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )
    assert (wd / "logs" / "claude.stdout.jsonl").exists()
    assert (wd / "logs" / "claude.stderr.log").exists()

async def test_command_contains_expected_args(tmp_path, patch_subprocess):
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    # Existing source so the prompt-volume mount survives the missing-source
    # skip guard added alongside the cred-bootstrap fix.
    chal = tmp_path / "CLAUDE.md"
    chal.write_text("# noop\n")
    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="claude-opus-4-7", timeout_s=30,
        container_cpus=2, container_memory="8g",
        prompt_volumes={chal: "/workspace/CLAUDE.md"},
    )
    cmd = patch_subprocess["cmd"]
    joined = " ".join(cmd)
    # Outer docker-run flags live as direct argv elements.
    assert "docker" in cmd[0] or "docker" in joined
    assert "run" in cmd
    assert "--rm" in cmd
    assert "--memory" in cmd and "8g" in cmd
    assert "--cpus" in cmd and "2" in cmd
    assert "-e" in cmd  # for ANTHROPIC_API_KEY
    assert "hydra-worker" in cmd
    # Inner `claude` invocation is wrapped in `sh -c "exec claude ..."` so
    # the cred-bootstrap step has somewhere to attach. Find it via the
    # wrapper string, not as bare argv elements.
    assert "sh" in cmd
    sh_payload = next(c for c in cmd if isinstance(c, str) and "exec claude" in c)
    assert "--model" in sh_payload
    assert "claude-opus-4-7" in sh_payload
    assert "--dangerously-skip-permissions" in sh_payload


async def test_credentials_dir_mounts_at_root_claude(tmp_path, patch_subprocess):
    """When credentials_dir is provided, it's bind-mounted read-only at a
    side path (`/root/.claude-host`) and copied into a writable
    `/root/.claude` at startup. Earlier versions mounted directly at
    `/root/.claude:ro`, which broke Claude Code's session-env writes."""
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    creds = tmp_path / "host_claude"
    creds.mkdir()
    (creds / "credentials.json").write_text("{}")

    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        credentials_dir=creds, model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )
    cmd = patch_subprocess["cmd"]
    joined = " ".join(str(c) for c in cmd)

    # Side-mount only — never at /root/.claude:ro directly.
    assert f"{creds.resolve()}:/root/.claude-host:ro" in joined
    assert f"{creds.resolve()}:/root/.claude:ro" not in joined
    # Bootstrap copies side-mount → writable /root/.claude before exec.
    assert any("cp -aT /root/.claude-host /root/.claude" in str(c) for c in cmd)
    # Inner command is exec'd so claude becomes the foregrounded PID,
    # not a child of the wrapping shell (so `docker stop` reaches it).
    assert any("exec claude" in str(c) for c in cmd)
    # No API key env var when credentials_dir is used
    assert not any(str(c).startswith("ANTHROPIC_API_KEY=") for c in cmd)


async def test_requires_either_creds_or_key(tmp_path, patch_subprocess):
    """Passing neither credentials_dir nor api_key must raise."""
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    with pytest.raises(ValueError, match="credentials_dir.*api_key"):
        await run_worker(
            name="x", workdir=wd, image="hydra-worker",
            model="m", timeout_s=30,
            container_cpus=1, container_memory="1g",
            prompt_volumes={},
        )


async def test_container_name_is_ascii_even_for_unicode_challenge_name(
    tmp_path, patch_subprocess
):
    """Docker requires container names match [a-zA-Z0-9][a-zA-Z0-9_.-]*.
    Challenge names can legitimately contain unicode (filesystem-safe), so
    the --name arg must be sanitized separately or Docker rejects the run."""
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)

    await run_worker(
        name="รหัสลับ", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )
    cmd = patch_subprocess["cmd"]
    name_idx = list(cmd).index("--name")
    container_name = cmd[name_idx + 1]
    assert container_name.isascii(), container_name
    import re as _re
    assert _re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", container_name), container_name
    assert container_name.startswith("hydra-")


async def test_docker_safe_name_helper():
    """Unit-level check for the sanitizer used in container naming."""
    from hydra.docker_worker import _docker_safe_name
    assert _docker_safe_name("simple-name") == "simple-name"
    # Pure-unicode name collapses to underscores, which get lstripped; falls
    # back to placeholder so `hydra-<name>-<uuid>` still starts alphanumeric
    # once the `hydra-` prefix is added.
    assert _docker_safe_name("รหัสลับ") == "x"
    assert _docker_safe_name("a/b c:d") == "a_b_c_d"
    # Empty-after-cleaning falls back to placeholder.
    assert _docker_safe_name("???") == "x"
    # Leading non-alphanumeric must be stripped.
    assert _docker_safe_name("-start") == "start"
    assert _docker_safe_name("_start") == "start"
    # Mixed ASCII + unicode keeps the ASCII portion.
    assert _docker_safe_name("webรถ1") == "web__1"
    # Long names are truncated to max_len.
    assert len(_docker_safe_name("a" * 100)) == 32


async def test_stdout_streamed_to_disk_during_run(tmp_path, monkeypatch):
    """Before the streaming fix, stdout/stderr were buffered in memory and
    only written after the container exited — so `tail -f` during a live
    run showed nothing. Now the log file must have content *before* proc
    exits."""
    log_path = tmp_path / "runs" / "x" / "logs" / "claude.stdout.jsonl"
    observed = {"mid_run_size": 0}

    class SlowWaitProc:
        """wait() deliberately yields several times so the stream task
        has a chance to drain stdout onto disk first. We sample the file
        size inside wait() to prove data landed on disk before wait
        returned."""
        def __init__(self):
            self.returncode = None
            self.stdout = FakeStreamReader(b"FLAG: flag{x}\n" * 100)
            self.stderr = FakeStreamReader(b"")
            self._killed = False

        async def wait(self):
            # Yield multiple times; the stream task should drain and flush.
            for _ in range(20):
                await asyncio.sleep(0.001)
            if log_path.exists():
                observed["mid_run_size"] = log_path.stat().st_size
            self.returncode = 0
            return 0

        def kill(self):
            self._killed = True
            self.returncode = -9

    proc = SlowWaitProc()
    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr(
        "hydra.docker_worker.asyncio.create_subprocess_exec", fake_create
    )

    wd = tmp_path / "runs" / "x"
    result = await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )

    # File was populated BEFORE wait() returned.
    assert observed["mid_run_size"] > 0, (
        "stdout was not written to disk during the run "
        f"(mid-run size: {observed['mid_run_size']})"
    )
    # Full content landed on disk.
    assert log_path.read_bytes() == b"FLAG: flag{x}\n" * 100
    # And the flag is still extractable from the returned stdout.
    assert "FLAG: flag{x}" in result.stdout


async def test_in_memory_buffer_is_bounded(tmp_path, monkeypatch):
    """A chatty agent (MB/GB of transcript) must not blow up RAM. The
    in-memory buffer caps at max_stdout_buffer; the disk copy stays
    complete."""
    class BigProc:
        def __init__(self):
            self.returncode = 0
            # 4 KB of noise, then a flag marker at the tail.
            self.stdout = FakeStreamReader(b"A" * 4096 + b"FLAG: flag{tail}\n")
            self.stderr = FakeStreamReader(b"")
            self._killed = False

        async def wait(self):
            await asyncio.sleep(0.01)
            return 0

        def kill(self):
            self._killed = True
            self.returncode = -9
            self.stdout.close()
            self.stderr.close()

    proc = BigProc()
    async def fake_create(*args, **kwargs):
        return proc
    monkeypatch.setattr(
        "hydra.docker_worker.asyncio.create_subprocess_exec", fake_create
    )

    wd = tmp_path / "runs" / "x"
    # Cap in-memory tail at 512 bytes — smaller than the 4 KB prefix, so
    # the head is dropped from RAM but preserved on disk.
    result = await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
        max_stdout_buffer=512,
    )

    # Returned stdout is bounded to ~512 bytes, plus at most one chunk
    # (chunk_size=65536) worth of overshoot before trimming — with a
    # 4 KB + marker input streamed in 64 KB reads, the stream is taken
    # in a single chunk and then trimmed to 512 bytes. Assert the bound
    # holds and the tail (where the flag is) survived.
    assert len(result.stdout) <= 512 + 1, f"stdout not bounded: {len(result.stdout)}"
    assert "FLAG: flag{tail}" in result.stdout
    # Disk copy is complete.
    on_disk = (wd / "logs" / "claude.stdout.jsonl").read_bytes()
    assert len(on_disk) == 4096 + len(b"FLAG: flag{tail}\n")


async def test_credentials_preferred_over_api_key(tmp_path, patch_subprocess):
    """If both are supplied, credentials_dir wins and api_key is ignored."""
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    creds = tmp_path / "host_claude"
    creds.mkdir()

    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        credentials_dir=creds, api_key="sk-backup",
        model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )
    cmd = patch_subprocess["cmd"]
    assert not any("ANTHROPIC_API_KEY=" in str(c) for c in cmd)
    assert any("/root/.claude-host:ro" in str(c) for c in cmd)


async def test_prompt_volume_with_missing_source_is_skipped(tmp_path, patch_subprocess):
    """A missing host-side prompt-volume source must NOT be mounted. Docker
    silently auto-creates an empty *directory* on the host when a bind-mount
    source doesn't exist, which then mounts as an empty dir inside the
    container — corrupting `/workspace/CLAUDE.md` (EISDIR on read), nuking
    the specialist agents, and stripping the exploit templates. Skipping
    leaves the path untouched both inside and outside the container."""
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)
    present = tmp_path / "CLAUDE.md"
    present.write_text("# real prompt asset\n")
    missing = tmp_path / "does-not-exist"
    assert not missing.exists()

    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={
            present: "/workspace/CLAUDE.md",
            missing: "/workspace/.claude",
        },
    )
    cmd = patch_subprocess["cmd"]
    joined = " ".join(str(c) for c in cmd)
    assert f"{present.resolve()}:/workspace/CLAUDE.md:ro" in joined
    assert "/workspace/.claude" not in joined
    # And docker must NOT have auto-created the missing host path.
    assert not missing.exists()


async def test_inner_command_quoting_preserves_special_chars(tmp_path, patch_subprocess):
    """The inner `claude -p <prompt>` is wrapped in `sh -c`, so the prompt
    must survive shell quoting intact — backticks especially. If the prompt
    leaks into shell evaluation, `FLAG: <flag>` becomes a command
    substitution that runs `<flag>` as a binary."""
    wd = tmp_path / "runs" / "x"
    (wd / "logs").mkdir(parents=True)

    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="m", timeout_s=30,
        container_cpus=1, container_memory="1g",
        prompt_volumes={},
    )
    cmd = patch_subprocess["cmd"]
    sh_cmd = next(c for c in cmd if isinstance(c, str) and "exec claude" in c)
    # The literal backtick'd marker is single-quoted, not exposed to sh.
    assert "`FLAG: <flag>`" in sh_cmd
    # And it lives inside a single-quoted region after the -p flag.
    assert "-p '" in sh_cmd


def test_run_worker_signature_accepts_container_name():
    """Regression: orchestrator must be able to hand run_worker a shared
    container_name so the sidecar Watchdog targets the real container."""
    import inspect
    from hydra.docker_worker import run_worker

    sig = inspect.signature(run_worker)
    assert "container_name" in sig.parameters
    # Default must be None so existing callers (and tests) keep working.
    assert sig.parameters["container_name"].default is None
