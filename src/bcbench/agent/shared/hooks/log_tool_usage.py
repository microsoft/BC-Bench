"""Copilot/Claude PreToolUse hook: log tool invocations to a JSONL file.

Reads the hook payload from stdin and appends one JSON line per call to the
path in BCBENCH_TOOL_LOG. Used by both Copilot CLI (Linux runners) and Claude
hooks via the `bash` field of the hook command spec; the legacy .ps1 in this
directory mirrors the same behavior for the Windows `powershell` field.
"""

import contextlib
import json
import os
import sys


def _extract_tool_name(payload: dict) -> str | None:
    name = payload.get("tool_name") or payload.get("toolName")
    if name != "lsp":
        return name

    args = payload.get("toolArgs") or payload.get("tool_input")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = None
    if isinstance(args, dict) and (op := args.get("operation")):
        return f"lsp:{op}"
    return name


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return

    name = _extract_tool_name(payload)
    log_path = os.environ.get("BCBENCH_TOOL_LOG")
    if not name or not log_path:
        return

    entry = {"tool_name": name, "timestamp": payload.get("timestamp", "")}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    with contextlib.suppress(Exception):
        # Never block tool execution — silently fail.
        main()
    sys.exit(0)
