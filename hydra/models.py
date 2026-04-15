from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["solved", "failed", "timeout", "error", "solved_uncertain"]

@dataclass(frozen=True)
class Challenge:
    name: str
    description: str
    files: list[Path] = field(default_factory=list)
    remote: str | None = None
    hints: list[str] = field(default_factory=list)
    category: str | None = None
    points: int | None = None

@dataclass(frozen=True)
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
