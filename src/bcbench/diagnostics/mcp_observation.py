import json
from dataclasses import dataclass, field
from typing import Any

from bcbench.diagnostics.mcp_diagnostics import AL_TOOL_NAMES, TARGET_TOOLS, SafeDiagnosticSnapshot

MAX_FRAME_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 1024


@dataclass
class _Frame:
    data: bytearray = field(default_factory=bytearray)
    oversized: bool = False


class McpObservation:
    def __init__(self, snapshot: SafeDiagnosticSnapshot) -> None:
        self.snapshot = snapshot
        self.state: dict[str, Any] = {
            "source": "actual_agent_stdio",
            "model_visibility": "unknown",
            "observation_issues": [],
            "lists": [],
            "target_call_requests": dict.fromkeys(TARGET_TOOLS, 0),
            "eof": {"client": False, "server": False},
            "process": {"stage": "proxy_started", "exit_code": None, "cleanup": "unobserved"},
        }
        snapshot.document["transport"] = self.state
        self._frames = {name: _Frame() for name in ("client", "server")}
        self._pending: dict[int | str, dict[str, Any]] = {}
        snapshot.save()

    def issue(self, category: str) -> None:
        if category not in self.state["observation_issues"]:
            self.state["observation_issues"].append(category)

    def feed(self, direction: str, data: bytes) -> None:
        frame = self._frames[direction]
        fragments = data.split(b"\n")
        for index, fragment in enumerate(fragments):
            if not frame.oversized:
                if len(frame.data) + len(fragment) > MAX_FRAME_BYTES:
                    frame.data.clear()
                    frame.oversized = True
                    self.issue("oversized_frame")
                else:
                    frame.data.extend(fragment)
            if index < len(fragments) - 1:
                if not frame.oversized:
                    self._message(direction, bytes(frame.data))
                frame.data.clear()
                frame.oversized = False

    def eof(self, direction: str) -> None:
        self.state["eof"][direction] = True
        frame = self._frames[direction]
        if frame.data or frame.oversized:
            self.issue("partial_frame_at_eof")
        frame.data.clear()

    def _message(self, direction: str, data: bytes) -> None:
        try:
            message = json.loads(data)
        except (ValueError, UnicodeError, RecursionError):
            self.issue("malformed_frame")
            return
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            self.issue("invalid_jsonrpc_message")
            return
        request_id = message.get("id")
        if not isinstance(request_id, str | int) or isinstance(request_id, bool):
            return
        if isinstance(request_id, str) and len(request_id) > 1024:
            self.issue("oversized_request_id")
            return
        if direction == "client":
            params = message.get("params", {})
            if not isinstance(params, dict):
                return
            if message.get("method") == "tools/call":
                tool = params.get("name")
                if isinstance(tool, str) and tool in TARGET_TOOLS:
                    self.state["target_call_requests"][tool] += 1
            elif message.get("method") == "tools/list":
                if len(self.state["lists"]) >= MAX_RECORDS:
                    self.issue("record_limit")
                    return
                if request_id in self._pending:
                    self._pending.pop(request_id)["status"] = "ambiguous_request_id"
                    self.issue("ambiguous_request_id")
                    return
                record = {"sequence": len(self.state["lists"]) + 1, "initial_page": params.get("cursor") is None, "status": "unobserved"}
                self.state["lists"].append(record)
                self._pending[request_id] = record
        elif "method" not in message and (record := self._pending.pop(request_id, None)) is not None:
            if "error" in message:
                record["status"] = "rpc_error"
                return
            result = message.get("result")
            tools = result.get("tools") if isinstance(result, dict) else None
            if not isinstance(tools, list) or any(not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"] for tool in tools):
                record["status"] = "malformed"
                return
            cursor = result.get("nextCursor")
            if cursor is not None and (not isinstance(cursor, str) or not cursor):
                record["status"] = "malformed"
                return
            record.update(status="observed", has_next_page=cursor is not None, tool_count=len(tools), tool_names=sorted({tool["name"] for tool in tools if tool["name"] in AL_TOOL_NAMES}))

    def save(self) -> None:
        self.state["observation_complete"] = not self.state["observation_issues"] and all(self.state["eof"].values())
        self.snapshot.save()
