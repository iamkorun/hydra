from pathlib import Path
from hydra.models import Challenge, Result

def test_challenge_minimal():
    c = Challenge(name="baby", description="solve me")
    assert c.name == "baby"
    assert c.description == "solve me"
    assert c.files == []
    assert c.remote is None
    assert c.hints == []
    assert c.category is None
    assert c.points is None

def test_challenge_rich():
    c = Challenge(
        name="pwn1",
        description="ret2libc",
        files=[Path("/tmp/pwn1")],
        remote="nc host 1337",
        hints=["use libc 2.35"],
        category="pwn",
        points=200,
    )
    assert c.files == [Path("/tmp/pwn1")]
    assert c.remote == "nc host 1337"
    assert c.hints == ["use libc 2.35"]
    assert c.points == 200

def test_result_solved():
    r = Result(
        name="baby",
        status="solved",
        flag="flag{abc}",
        duration_s=12.3,
        started_at="2026-04-14T00:00:00Z",
        finished_at="2026-04-14T00:00:12Z",
        worker_exit_code=0,
        work_dir="./runs/baby/",
    )
    assert r.status == "solved"
    assert r.flag == "flag{abc}"
    assert r.reason is None

def test_result_failed_has_reason():
    r = Result(
        name="x",
        status="timeout",
        flag=None,
        duration_s=3600.0,
        started_at="...",
        finished_at="...",
        worker_exit_code=124,
        work_dir="./runs/x/",
        reason="wall-clock timeout",
    )
    assert r.flag is None
    assert r.reason == "wall-clock timeout"
