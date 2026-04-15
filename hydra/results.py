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
        # Ensure output dirs exist up-front so the first append() doesn't
        # crash if the user pointed --jsonl / --flags-out / --results at a
        # path whose parent is not yet created.
        for p in (jsonl_path, flags_path, results_path):
            p.parent.mkdir(parents=True, exist_ok=True)
        # Pre-load existing jsonl so finalize sees everything (supports resume).
        if jsonl_path.exists():
            for line in jsonl_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    self._results.append(Result(**d))
                except (json.JSONDecodeError, TypeError, ValueError):
                    # Tolerate malformed or schema-drifted lines during
                    # resume. We still want to run new challenges even if
                    # an old entry can't be reconstructed.
                    continue

    def append(self, r: Result) -> None:
        self._results.append(r)
        with self.jsonl_path.open("a") as f:
            f.write(json.dumps(asdict(r), default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._write_flags_json()

    def _latest_by_name(self) -> list[Result]:
        # Coalesce by name: a challenge may appear multiple times in the
        # jsonl (e.g., a prior-run failure followed by a --retry-failed
        # success). The latest entry is authoritative; without coalescing,
        # the same name could appear in both `data` and `__failed__` (or
        # be counted twice in the summary).
        latest: dict[str, Result] = {}
        for r in self._results:
            latest[r.name] = r
        return list(latest.values())

    def _write_flags_json(self) -> None:
        data: dict = {}
        failed: list[str] = []
        for r in self._latest_by_name():
            if r.status in ("solved", "solved_uncertain") and r.flag:
                data[r.name] = r.flag
            else:
                failed.append(r.name)
        if failed:
            data["__failed__"] = failed
        _atomic_write(self.flags_path, json.dumps(data, indent=2, ensure_ascii=False))

    def finalize(self, *, run_id: str) -> None:
        results = self._latest_by_name()
        summary = {
            "total": len(results),
            "solved": sum(1 for r in results if r.status == "solved"),
            "solved_uncertain": sum(
                1 for r in results if r.status == "solved_uncertain"
            ),
            "failed": sum(1 for r in results if r.status == "failed"),
            "timeout": sum(1 for r in results if r.status == "timeout"),
            "error": sum(1 for r in results if r.status == "error"),
            "total_duration_s": sum(r.duration_s for r in results),
        }
        if summary["total"] > 0:
            summary["solve_rate"] = round(summary["solved"] / summary["total"], 4)
        else:
            summary["solve_rate"] = 0.0
        payload = {
            "run_id": run_id,
            "summary": summary,
            "challenges": [asdict(r) for r in results],
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
