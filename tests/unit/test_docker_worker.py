import asyncio
from pathlib import Path
import pytest
from hydra.docker_worker import run_worker, WorkerResult

class FakeProc:
    def __init__(self, *, returncode=0, stdout=b"FLAG: flag{x}\n", stderr=b"", delay=0.01):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._delay = delay
        self._killed = False

    async def communicate(self):
        await asyncio.sleep(self._delay)
        if self._killed:
            self.returncode = -9
        return self._stdout, self._stderr

    def kill(self):
        self._killed = True

    async def wait(self):
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
        model="claude-opus-4-6",
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
    monkeypatch.setattr("hydra.docker_worker._docker_stop", fake_stop)

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
    await run_worker(
        name="x", workdir=wd, image="hydra-worker",
        api_key="sk", model="claude-opus-4-6", timeout_s=30,
        container_cpus=2, container_memory="8g",
        prompt_volumes={Path("/h/CLAUDE.md"): "/workspace/CLAUDE.md"},
    )
    cmd = patch_subprocess["cmd"]
    joined = " ".join(cmd)
    assert "docker" in cmd[0] or "docker" in joined
    assert "run" in cmd
    assert "--rm" in cmd
    assert "--memory" in cmd and "8g" in cmd
    assert "--cpus" in cmd and "2" in cmd
    assert "-e" in cmd  # for ANTHROPIC_API_KEY
    assert "hydra-worker" in cmd
    assert any("claude" in c for c in cmd)
    assert "--model" in cmd
    assert "claude-opus-4-6" in cmd
