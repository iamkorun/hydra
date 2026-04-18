import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, UTC
from pathlib import Path

from hydra.heartbeat import Heartbeat, fmt_duration
from hydra.normalize import normalize_challenges, NormalizationError, safe_name
from hydra.orchestrator import Orchestrator, OrchestratorConfig
from hydra.results import ResultsWriter, load_jsonl_names

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_CREDENTIALS_DIR = Path.home() / ".claude"

@dataclass
class ResolvedConfig:
    challenges_path: str
    parallel: int | None
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
    attempts: int = 1
    watchdog_enabled: bool = True
    watchdog_cost_cap_usd: float = 10.0
    watchdog_mem_kill_pct: float = 90.0
    watchdog_max_same_bash_repeats: int = 3
    watchdog_max_solver_variants: int = 5
    watchdog_idle_work_timeout_s: float = 180.0

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hydra",
        description="Autonomous CTF batch solver — JSON in, flags out.",
    )
    p.add_argument("challenges", help="Path to challenges JSON (or '-' for stdin)")
    p.add_argument(
        "--parallel", type=int, default=None,
        help="Concurrent workers (containers). Default: number of challenges in the input JSON.",
    )
    p.add_argument("--timeout", type=int, default=3600, help="Per-challenge wall-clock (s)")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Claude model")
    p.add_argument(
        "--attempts", type=int, default=1,
        help="pass@k: run K parallel attempts per challenge, first flag wins. "
             "Each attempt consumes a --parallel slot. Palisade arxiv 2412.02776 "
             "reports 83%%→95%% on InterCode-CTF moving from k=1 to k=10.",
    )
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
    p.add_argument(
        "--no-watchdog", action="store_true",
        help="Disable the deterministic sidecar watchdog. Use when "
             "debugging the agent itself and you don't want auto-kill.",
    )
    p.add_argument(
        "--watchdog-cost-cap", type=float, default=10.0, metavar="USD",
        help="Kill a worker once estimated token cost exceeds this cap.",
    )
    p.add_argument(
        "--watchdog-mem-kill-pct", type=float, default=90.0, metavar="PCT",
        help="Kill cleanly when container RSS reaches this percent of "
             "its --memory limit (pre-empts kernel OOM).",
    )
    p.add_argument(
        "--watchdog-max-bash-repeats", type=int, default=3, metavar="N",
        help="Kill when the same Bash command prefix fires N+ times.",
    )
    p.add_argument(
        "--watchdog-max-solver-variants", type=int, default=5, metavar="N",
        help="Kill when the agent writes more than N files matching "
             "/workspace/work/{solve,probe,exploit}NNN.py.",
    )
    p.add_argument(
        "--watchdog-idle-work-timeout", type=float, default=180.0, metavar="S",
        help="Kill when workdir/work/ mtime is stale longer than S "
             "seconds while the agent is still emitting tool_uses.",
    )
    return p

def resolve_config(ns: argparse.Namespace, *, root: Path) -> ResolvedConfig:
    creds_dir, api_key = _resolve_auth(ns)
    if ns.attempts < 1:
        print("error: --attempts must be >= 1", file=sys.stderr)
        raise SystemExit(2)
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
        attempts=ns.attempts,
        watchdog_enabled=not ns.no_watchdog,
        watchdog_cost_cap_usd=ns.watchdog_cost_cap,
        watchdog_mem_kill_pct=ns.watchdog_mem_kill_pct,
        watchdog_max_same_bash_repeats=ns.watchdog_max_bash_repeats,
        watchdog_max_solver_variants=ns.watchdog_max_solver_variants,
        watchdog_idle_work_timeout_s=ns.watchdog_idle_work_timeout,
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
    # Apply the same safe_name() transform that normalize_challenges uses,
    # so users can pass either the raw JSON name or the sanitized form. A
    # raw name like "foo bar" would otherwise silently match nothing once
    # the challenge has been renamed to "foo-bar".
    if not spec:
        return None
    names = {s.strip() for s in spec.split(",") if s.strip()}
    if not names:
        return None
    return {safe_name(n) for n in names}

def _read_input(path: str) -> list:
    raw = sys.stdin.read() if path == "-" else Path(path).read_text()
    return json.loads(raw)

def _hydra_repo_root() -> Path:
    """Return the hydra checkout root (where CLAUDE.md / .claude / exploits
    ship as agent assets). Resolved from the installed package location so
    it works regardless of the user's cwd — running `hydra` from anywhere
    still finds the assets."""
    return Path(__file__).resolve().parent.parent


def _prompt_volumes(root: Path | None = None) -> dict[Path, str]:
    """Bind mounts that ship the hydra agent assets into /workspace.

    Sources resolve to the hydra checkout, not the user's cwd. Earlier
    versions used `Path.cwd()` and Docker silently auto-created empty
    host directories at every missing source — which then mounted as
    empty dirs inside the container, so the inner agent saw an empty
    `/workspace/CLAUDE.md` directory (EISDIR on read), no specialists,
    and no exploit templates."""
    base = root if root is not None else _hydra_repo_root()
    return {
        base / "CLAUDE.md": "/workspace/CLAUDE.md",
        base / ".claude": "/workspace/.claude",
        base / "exploits": "/workspace/exploits",
    }

def _resolve_parallel(requested: int | None, n_challenges: int) -> int:
    # Default --parallel to the post-filter challenge count so unattended
    # runs fan out fully without a manual cap. User-supplied values always
    # win (even 0/negative — argparse trusts them; catching that here would
    # hide a real config bug). Floor at 1 when the JSON has zero entries
    # so asyncio.Semaphore(0) can't deadlock the orchestrator.
    if requested is not None:
        return requested
    return max(1, n_challenges)


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
        filtered = [c for c in challenges if c.name in cfg.only_filter]
        if not filtered:
            # Silent empty runs are a classic user trap. Flag it but keep
            # returning 2 so shell pipelines can detect the mistake.
            available = ", ".join(sorted(c.name for c in challenges)[:10])
            print(
                f"error: --only {sorted(cfg.only_filter)} matched no "
                f"challenges. Available (first 10): {available}",
                file=sys.stderr,
            )
            return 2
        challenges = filtered

    parallel = _resolve_parallel(cfg.parallel, len(challenges))

    skip = _compute_skips(cfg)

    if cfg.dry_run:
        print(f"dry-run: {len(challenges)} challenges normalized", flush=True)
        return 0

    writer = ResultsWriter(
        jsonl_path=cfg.jsonl_path,
        flags_path=cfg.flags_path,
        results_path=cfg.results_path,
    )
    orch_cfg = OrchestratorConfig(
        parallel=parallel,
        timeout_s=cfg.timeout,
        model=cfg.model,
        image=cfg.image,
        credentials_dir=cfg.credentials_dir,
        api_key=cfg.api_key,
        runs_dir=cfg.runs_dir,
        failures_dir=cfg.failures_dir,
        prompt_volumes=_prompt_volumes(),
        skip_names=skip,
        attempts=cfg.attempts,
        watchdog_enabled=cfg.watchdog_enabled,
        watchdog_cost_cap_usd=cfg.watchdog_cost_cap_usd,
        watchdog_mem_kill_pct=cfg.watchdog_mem_kill_pct,
        watchdog_max_same_bash_repeats=cfg.watchdog_max_same_bash_repeats,
        watchdog_max_solver_variants=cfg.watchdog_max_solver_variants,
        watchdog_idle_work_timeout_s=cfg.watchdog_idle_work_timeout_s,
    )
    run_id = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    n_pending = len(challenges) - len(skip & {c.name for c in challenges})
    print(
        f"\u25b6 solving {n_pending} challenge(s) "
        f"(parallel={parallel}, timeout={cfg.timeout}s, "
        f"attempts={cfg.attempts}, model={cfg.model})",
        flush=True,
    )
    t0 = time.monotonic()
    async with Heartbeat() as hb:
        orch = Orchestrator(orch_cfg, writer=writer, heartbeat=hb)
        try:
            await orch.run(challenges)
        finally:
            writer.finalize(run_id=run_id)
    wall_s = time.monotonic() - t0
    _print_summary(writer, wall_s=wall_s)
    return 0 if any(r.status == "solved" for r in writer._results) else 1


def _print_summary(writer: ResultsWriter, *, wall_s: float) -> None:
    results = writer._latest_by_name()
    if not results:
        return
    solved = sum(1 for r in results if r.status == "solved")
    total = len(results)
    cost = sum(r.usage.cost_usd for r in results)
    # `duration_s` is each worker's wall-clock; summed it's the batch's
    # time-on-task across parallel slots (useful for $/compute sizing).
    # `wall_s` is the orchestrator's real elapsed clock — what the user
    # actually waited. Report both so a fast parallel batch doesn't look
    # as slow as its summed runtime.
    agg = sum(r.duration_s for r in results)
    cost_str = f", ${cost:.2f}" if cost else ""
    print(
        f"\u25b6 solved {solved}/{total} in {fmt_duration(wall_s)} wall "
        f"({fmt_duration(agg)} agg){cost_str}",
        flush=True,
    )

def _default_out_dir(challenges_path: str, cwd: Path) -> Path:
    """Pick the root dir used for default output paths.

    Derived from the input JSON filename so running `hydra phase-1.json`
    and `hydra phase-2.json` back-to-back in the same cwd produces
    `./phase-1/` and `./phase-2/` with independent runs/, results.*,
    flags.json, and failures/. Before: both dumped into cwd, and phase-2
    silently inherited phase-1's jsonl as resume state.

    Stdin (`-`) falls back to cwd since there's no filename to key off.
    Explicit --runs-dir / --results / --jsonl / --flags-out still win,
    so existing pipelines aren't broken.
    """
    if challenges_path == "-":
        return cwd
    stem = Path(challenges_path).stem
    return cwd / stem if stem else cwd


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    out_dir = _default_out_dir(ns.challenges, Path.cwd())
    cfg = resolve_config(ns, root=out_dir)
    return asyncio.run(_run(cfg))

if __name__ == "__main__":
    raise SystemExit(main())
