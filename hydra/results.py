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
