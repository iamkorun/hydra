from pathlib import Path
import pytest
from hydra.models import Challenge
from hydra.workdir import build_workdir

def test_creates_expected_layout(tmp_path: Path):
    runs = tmp_path / "runs"
    c = Challenge(name="baby-rsa", description="solve this")
    wd = build_workdir(c, runs_dir=runs)

    assert wd == runs / "baby-rsa"
    assert (wd / "challenge").is_dir()
    assert (wd / "work").is_dir()
    assert (wd / "logs").is_dir()
    assert (wd / "flag.txt").exists()
    assert (wd / "flag.txt").read_text() == ""

def test_readme_contains_description(tmp_path: Path):
    c = Challenge(name="x", description="classic ret2libc")
    wd = build_workdir(c, runs_dir=tmp_path)
    readme = (wd / "challenge" / "README.md").read_text()
    assert "# x" in readme
    assert "classic ret2libc" in readme

def test_readme_contains_metadata(tmp_path: Path):
    c = Challenge(
        name="x", description="y", category="pwn", points=200,
        remote="nc host 1337",
    )
    wd = build_workdir(c, runs_dir=tmp_path)
    readme = (wd / "challenge" / "README.md").read_text()
    assert "**Category:** pwn" in readme
    assert "**Points:** 200" in readme
    assert "nc host 1337" in readme

def test_hints_written_separately(tmp_path: Path):
    c = Challenge(name="x", description="y", hints=["try harder", "think outside the box"])
    wd = build_workdir(c, runs_dir=tmp_path)
    hints = (wd / "challenge" / "hints.md").read_text()
    assert "try harder" in hints
    assert "think outside the box" in hints

def test_no_hints_no_file(tmp_path: Path):
    c = Challenge(name="x", description="y")
    wd = build_workdir(c, runs_dir=tmp_path)
    assert not (wd / "challenge" / "hints.md").exists()

def test_copies_files(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "chal.bin").write_bytes(b"\x7fELF...")
    c = Challenge(name="x", description="y", files=[src / "chal.bin"])
    wd = build_workdir(c, runs_dir=tmp_path / "runs")
    assert (wd / "challenge" / "chal.bin").read_bytes() == b"\x7fELF..."

def test_missing_file_logged_not_fatal(tmp_path: Path):
    c = Challenge(name="x", description="y", files=[Path("/nonexistent/nope.bin")])
    wd = build_workdir(c, runs_dir=tmp_path / "runs")
    warnings = (wd / "logs" / "warnings.log").read_text()
    assert "nonexistent" in warnings

def test_filename_collision_suffixes(tmp_path: Path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    (tmp_path / "a" / "dup.txt").write_text("A")
    (tmp_path / "b" / "dup.txt").write_text("B")
    c = Challenge(name="x", description="y", files=[
        tmp_path / "a" / "dup.txt", tmp_path / "b" / "dup.txt"
    ])
    wd = build_workdir(c, runs_dir=tmp_path / "runs")
    files = sorted(p.name for p in (wd / "challenge").glob("dup*"))
    assert "dup.txt" in files
    assert any(f.startswith("dup_") for f in files)
