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
