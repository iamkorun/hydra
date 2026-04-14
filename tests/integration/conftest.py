import os
import stat
from pathlib import Path

import pytest

FAKE = Path(__file__).parent / "fake_docker.py"


@pytest.fixture
def fake_docker(monkeypatch, tmp_path):
    """Prepend a tmp dir containing a `docker` shim to PATH."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "docker"
    shim.write_text(
        f"#!/usr/bin/env python3\n"
        f"import runpy\n"
        f"runpy.run_path({str(FAKE)!r}, run_name='__main__')\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")

    scenario_path = tmp_path / "scenario.json"
    monkeypatch.setenv("FAKE_DOCKER_SCENARIO", str(scenario_path))
    return scenario_path
