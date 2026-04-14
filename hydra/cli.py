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
DEFAULT_CREDENTIALS_DIR = Path.home() / ".claude"

@dataclass
class ResolvedConfig:
    challenges_path: str
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
    credentials_dir: Path | None = None
    api_key: str | None = None
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
    p.add_argument(
        "--credentials-dir",
        default=None,
        help="Host dir to mount at /root/.claude (default: ~/.claude if present). "
             "When set, containerized `claude -p` uses host subscription auth.",
    )
    p.add_argument(
        "--use-api-key",
        action="store_true",
        help="Force ANTHROPIC_API_KEY auth even if ~/.claude exists.",
    )
    return p

def resolve_config(ns: argparse.Namespace, *, root: Path) -> ResolvedConfig:
    creds_dir, api_key = _resolve_auth(ns)
    return ResolvedConfig(
        challenges_path=ns.challenges,
        credentials_dir=creds_dir,
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

def _resolve_auth(ns: argparse.Namespace) -> tuple[Path | None, str | None]:
    """Return (credentials_dir, api_key). At least one must be non-None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None

    # Explicit --use-api-key: skip credential-dir resolution.
    if getattr(ns, "use_api_key", False):
        if not api_key:
            print(
                "error: --use-api-key set but ANTHROPIC_API_KEY is empty",
                file=sys.stderr,
            )
            raise SystemExit(2)
        return None, api_key

    # Explicit --credentials-dir takes priority.
    if getattr(ns, "credentials_dir", None):
        creds = Path(ns.credentials_dir).expanduser()
        if not creds.is_dir():
            print(f"error: --credentials-dir {creds} does not exist", file=sys.stderr)
            raise SystemExit(2)
        return creds, api_key  # api_key tagged along as fallback

    # Default: prefer ~/.claude subscription auth if it looks valid.
    if DEFAULT_CREDENTIALS_DIR.is_dir() and _looks_logged_in(DEFAULT_CREDENTIALS_DIR):
        return DEFAULT_CREDENTIALS_DIR, api_key

    # Fall back to API key.
    if api_key:
        return None, api_key

    print(
        "error: no auth — neither ~/.claude subscription credentials nor "
        "ANTHROPIC_API_KEY env var found.\n"
        "Fix: run `claude` once on the host to log in (subscription), OR set "
        "`export ANTHROPIC_API_KEY=sk-ant-...` (API key).",
        file=sys.stderr,
    )
    raise SystemExit(2)

def _looks_logged_in(claude_dir: Path) -> bool:
    """Heuristic: Claude Code stores credentials/state in ~/.claude. Any of
    these indicate a logged-in state."""
    candidates = ("credentials.json", ".credentials.json", "settings.json")
    return any((claude_dir / n).is_file() for n in candidates)

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
        credentials_dir=cfg.credentials_dir,
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
