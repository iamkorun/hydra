#!/bin/sh
# analyzeHeadless wrapper: cap Ghidra invocations per container so the
# agent cannot burn its token budget re-decompiling. Override with
# GHIDRA_MAX_CALLS=N if you legitimately need more passes.
set -eu

GHIDRA_REAL="/opt/ghidra_12.0.4_PUBLIC/support/analyzeHeadless"
STATE_FILE="${GHIDRA_STATE_FILE:-/tmp/.ghidra_call_count}"
MAX_CALLS="${GHIDRA_MAX_CALLS:-2}"

count=0
if [ -f "$STATE_FILE" ]; then
    count=$(cat "$STATE_FILE" 2>/dev/null || echo 0)
fi

if [ "$count" -ge "$MAX_CALLS" ]; then
    cat >&2 <<EOF
error: analyzeHeadless call cap reached ($count/$MAX_CALLS).

Ghidra decompilation burns ~20K cache tokens per invocation and
rarely reveals more than: (a) reading the source if you have it, or
(b) curl-probing the live endpoint. You've already used $count pass(es).

Do this instead:
  - Web chal: fuzz the HTTP surface (curl every endpoint with junk,
    SQLi, path traversal, oversized payloads).
  - Pwn chal: write pwntools and send bytes to remote to confirm
    the vuln class before reversing more.
  - If more decompilation is genuinely justified, export
    GHIDRA_MAX_CALLS=N and document the reason in ./work/plan.md.

Exiting with code 2.
EOF
    exit 2
fi

count=$((count + 1))
echo "$count" > "$STATE_FILE"
exec "$GHIDRA_REAL" "$@"
