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
