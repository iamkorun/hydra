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
