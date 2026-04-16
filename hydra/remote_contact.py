"""Did the agent actually contact the challenge remote?

A flag extracted from a run where the agent never opened a socket
to `<host>:<port>` is suspect by construction — it must have come
from README prose, a hardcoded binary string, or a hallucination,
not from the challenge's response. Parse the stream-json log
looking for bash commands / tool_use inputs mentioning the remote
host or port, and report a verdict.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_URL_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+\-.]*://", re.IGNORECASE)


def parse_remote(remote: str | None) -> tuple[str | None, int | None]:
    """Parse a challenge remote spec into (host, port).

    Accepts:
      - `host:port` (bare TCP): returns (host, port).
      - `http://host:port[/path]` (URL): returns (host, port).
      - `hostname` (no port): returns (hostname, None).
      - None / empty: returns (None, None).
    """
    if not remote:
        return None, None
    s = remote.strip()
    s = _URL_SCHEME_RE.sub("", s)
    s = s.split("/", 1)[0]
    if ":" in s:
        host, port_s = s.rsplit(":", 1)
        try:
            return host, int(port_s)
        except ValueError:
            return host, None
    return s, None


def was_remote_contacted(log_file: Path, remote: str | None) -> bool:
    """Return True if the run's log contains evidence that the agent
    addressed the given remote.

    Heuristic: scan every assistant tool_use `input` payload (JSON-
    stringified) for the host or port substring. Generous on purpose
    — we want a false-positive in the *contact* sense (trust the run)
    rather than demote every genuine solve.

    Returns True when:
      - `remote` is None or empty (nothing to check).
      - The log file does not exist yet (no evidence either way —
        default to trusting, consistent with the "generous" policy).
      - Any tool_use input mentions the host or the port (as string).
    """
    if not remote:
        return True
    host, port = parse_remote(remote)
    if host is None:
        return True
    if not log_file.exists():
        return True

    needles: list[str] = [host]
    if port is not None:
        needles.append(str(port))

    with log_file.open("r", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") != "assistant":
                continue
            content = msg.get("message", {}).get("content") or []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_use":
                    continue
                payload = json.dumps(block.get("input", {}), ensure_ascii=False)
                for needle in needles:
                    if needle in payload:
                        return True
    return False
