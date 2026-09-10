from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from bcbench.playbooks import route_playbook_for_paths

_TOOL_NAME = "route_bug_fix_playbook"


def _write_message(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _tool_definition() -> dict[str, Any]:
    return {
        "name": _TOOL_NAME,
        "description": "Route confirmed repository-relative source paths and return the matching playbook content. Call exactly once after root-cause investigation and before editing source files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirmed_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                }
            },
            "required": ["confirmed_paths"],
            "additionalProperties": False,
        },
    }


def _result(request_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _handle_request(playbook_dir: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None:
        return None

    match method:
        case "initialize":
            params = request.get("params")
            protocol_version = params.get("protocolVersion") if isinstance(params, dict) else None
            return _result(
                request_id,
                {
                    "protocolVersion": protocol_version or "2025-11-25",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "bcbench-playbooks", "version": "1.0"},
                    "instructions": "Route confirmed repository source paths to at most one BC bug-fix playbook.",
                },
            )
        case "ping":
            return _result(request_id, {})
        case "tools/list":
            return _result(request_id, {"tools": [_tool_definition()]})
        case "tools/call":
            params = request.get("params")
            if not isinstance(params, dict) or params.get("name") != _TOOL_NAME:
                return _error(request_id, -32602, f"Unknown tool: {params.get('name') if isinstance(params, dict) else None}")

            arguments = params.get("arguments")
            confirmed_paths = arguments.get("confirmed_paths") if isinstance(arguments, dict) else None
            if not isinstance(confirmed_paths, list) or not confirmed_paths or not all(isinstance(path, str) for path in confirmed_paths):
                return _error(request_id, -32602, "confirmed_paths must be a non-empty list of strings")

            route = route_playbook_for_paths(playbook_dir, confirmed_paths).model_dump(mode="json")
            return _result(
                request_id,
                {
                    "content": [{"type": "text", "text": json.dumps(route)}],
                    "structuredContent": route,
                    "isError": False,
                },
            )
        case _:
            return _error(request_id, -32601, f"Method not found: {method}")


def run_server(playbook_dir: Path) -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _write_message(_error(None, -32700, "Parse error"))
            continue
        if not isinstance(request, dict):
            _write_message(_error(None, -32600, "Invalid Request"))
            continue
        response = _handle_request(playbook_dir, request)
        if response is not None:
            _write_message(response)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("playbook_dir", type=Path)
    args = parser.parse_args()
    run_server(args.playbook_dir)


if __name__ == "__main__":
    main()
