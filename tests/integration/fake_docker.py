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

    # Write flag.txt inside the mounted workdir if requested, and drop a
    # scratch artifact so the flag_gate's `no_scratch` WARN doesn't fire
    # on a simulated solve. Real agents touch /workspace/work/ to derive;
    # this sentinel models that minimally.
    for src, dst in mounts:
        if dst == "/workspace":
            work = Path(src) / "work"
            work.mkdir(parents=True, exist_ok=True)
            (work / "fake-scratch").write_text("simulated derivation\n")
            if "flag_file" in matched:
                (Path(src) / "flag.txt").write_text(matched["flag_file"])
            break

    sys.stdout.write(matched.get("stdout", ""))
    sys.stderr.write(matched.get("stderr", ""))
    return matched.get("exit_code", 0)


if __name__ == "__main__":
    sys.exit(main())
