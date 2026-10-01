import json
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from bcbench.agent.shared.diagnostic_process import DiagnosticProcess, DiagnosticReadError
from bcbench.agent.shared.mcp_diagnostics import AL_TOOL_NAMES, TARGET_TOOLS, SafeDiagnosticSnapshot

_SERVER_STATUSES = frozenset({"connected", "failed", "needs-auth", "pending", "disabled", "stopped", "not_configured"})
_ERROR_TYPES = frozenset({"authentication", "authorization", "quota", "rate_limit", "context_limit", "query"})
_ERROR_MARKERS = {
    "authentication": re.compile(r"\b(?:unauthorized|authentication failed|invalid credentials|HTTP 401)\b", re.IGNORECASE),
    "authorization": re.compile(r"\b(?:forbidden|access denied|permission denied|HTTP 403)\b", re.IGNORECASE),
    "connection": re.compile(r"\b(?:ECONNREFUSED|ENOTFOUND|connection refused|connection reset|no such host)\b", re.IGNORECASE),
    "timeout": re.compile(r"\b(?:ETIMEDOUT|timed out|timeout)\b", re.IGNORECASE),
    "compilation": re.compile(r"\b(?:compilation failed|build failed|error AL\d{4})\b", re.IGNORECASE),
    "dependency": re.compile(r"\b(?:missing dependency|dependencies could not be resolved|AL1022)\b", re.IGNORECASE),
}


def _error_markers(error: object) -> list[str]:
    # Fixed labels only, from explicitly reported errors, never arbitrary successful tool output.
    if isinstance(error, dict):
        fields = (value for key, value in error.items() if key in ("code", "message"))
        text = "\n".join(field[:8192] for field in fields if isinstance(field, str))
    else:
        text = error[:8192] if isinstance(error, str) else ""
    return [name for name, pattern in _ERROR_MARKERS.items() if pattern.search(text)]


def _al_tool(data: dict) -> str | None:
    server = data.get("mcpConfigServerName", data.get("mcpServerName"))
    if server not in (None, "altool"):
        return None
    name = data.get("mcpToolName")
    if server == "altool" and isinstance(name, str) and name in AL_TOOL_NAMES:
        return name
    # The 36715220745 transcript uses e.g. altool-al_compile, not bare al_compile.
    label = data.get("toolName")
    if isinstance(label, str) and label.startswith("altool-") and label[7:] in AL_TOOL_NAMES:
        return label[7:]
    return None


def _completion(data: dict) -> dict[str, Any]:
    success = data.get("success")
    success = success if isinstance(success, bool) else None
    result = data.get("result")
    valid_result = isinstance(result, dict) and isinstance(result.get("content"), str)
    semantic_error: bool | None = None
    malformed_envelope = False
    content = result if isinstance(result, dict) and isinstance(result.get("content"), list) else None
    envelope_source = "direct_result" if content is not None else "unobserved"
    if valid_result:
        try:
            content = json.loads(result["content"])
        except (ValueError, RecursionError):
            content = None
        envelope_source = "json_result_content"
    # Only inspect an MCP envelope, not arbitrary error prose or AL source text.
    if isinstance(content, dict) and "isError" in content:
        if isinstance(content.get("isError"), bool) and isinstance(content.get("content"), list):
            semantic_error = content["isError"]
        else:
            malformed_envelope = True
    error_markers = set(_error_markers(data.get("error")))
    if semantic_error is True and isinstance(content, dict):
        for block in content["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                error_markers.update(_error_markers(block.get("text")))
    outcome = "unavailable"
    if success is False or semantic_error is True:
        outcome = "failed"
    elif success is True and valid_result and not malformed_envelope and data.get("error") is None:
        outcome = "succeeded"
    return {
        "completion": "observed",
        "cli_reported_success": success,
        "mcp_is_error_in_result_envelope": semantic_error,
        "mcp_envelope_source": envelope_source if semantic_error is not None else "unobserved",
        "execution_outcome": outcome,
        "execution_outcome_basis": "mcp_result_envelope_is_error" if semantic_error is True else "copilot_success_flag" if outcome != "unavailable" else "unavailable",
        # A CLI success or MCP isError=false does not establish that AL compiled/published/tests passed.
        "al_operation_outcome": "unavailable",
        "reported_error_markers": sorted(error_markers),
        "error_details": "withheld" if data.get("error") is not None or semantic_error is True else "not_observed",
    }


class CopilotDiagnostics:
    def __init__(self, snapshot: SafeDiagnosticSnapshot) -> None:
        self.snapshot = snapshot
        self.state: dict[str, Any] = {
            "source": "copilot_json_stdout",
            "stderr": "discarded_for_safety",
            "process": "agent",
            "model_tool_catalog": "unobserved",
            "model_reason_for_not_invoking": "unavailable",
            "stream": "not_started",
            "invalid_event_count": 0,
            "tool_start_count": 0,
            "tool_completion_count": 0,
            "unmatched_al_completion_count": 0,
            "server_status_observations": [],
            "server_error_markers": [],
            "calls": [],
            "stop": {"process": "not_started", "result_event": "unobserved", "shutdown_event": "unobserved", "session_errors": []},
        }
        self._calls: dict[str, dict[str, Any]] = {}
        snapshot.document["agent"] = self.state
        self.save()

    def save(self) -> None:
        self.state["targets"] = {
            tool: {
                "invocation": (
                    "observed"
                    if any(call["tool"] == tool for call in self.state["calls"])
                    else "not_invoked_in_observed_stream"
                    if self.state["stream"] == "eof" and not self.state["invalid_event_count"] and not self.state["unmatched_al_completion_count"]
                    else "not_observed"
                ),
                "model_visibility": "invocation_observed" if any(call["tool"] == tool for call in self.state["calls"]) else "unknown",
                "execution_success_count": sum(call["tool"] == tool and call["execution_outcome"] == "succeeded" for call in self.state["calls"]),
                "execution_failure_count": sum(call["tool"] == tool and call["execution_outcome"] == "failed" for call in self.state["calls"]),
                "incomplete_count": sum(call["tool"] == tool and call["completion"] == "not_observed" for call in self.state["calls"]),
                "unavailable_outcome_count": sum(call["tool"] == tool and call["execution_outcome"] == "unavailable" for call in self.state["calls"]),
            }
            for tool in TARGET_TOOLS
        }
        self.snapshot.save()

    def observe_line(self, line: str) -> None:
        try:
            event = json.loads(line)
        except (ValueError, RecursionError):
            self.state["invalid_event_count"] += 1
            self.save()
            return
        if not isinstance(event, dict):
            self.state["invalid_event_count"] += 1
            self.save()
            return
        kind = event.get("type")
        data = event.get("data")
        if kind in ("tool.execution_start", "tool.execution_complete") and (
            not isinstance(data, dict) or not isinstance(data.get("toolCallId"), str) or not data["toolCallId"] or (kind == "tool.execution_start" and not isinstance(data.get("toolName"), str))
        ):
            self.state["invalid_event_count"] += 1
        data = data if isinstance(data, dict) else {}
        if kind == "tool.execution_start":
            self.state["tool_start_count"] += 1
            if tool := _al_tool(data):
                call: dict[str, Any] = {
                    "sequence": len(self.state["calls"]) + 1,
                    "tool": tool,
                    "completion": "not_observed",
                    "execution_outcome": "incomplete",
                    "al_operation_outcome": "unavailable",
                }
                self.state["calls"].append(call)
                call_id = data.get("toolCallId")
                if isinstance(call_id, str) and call_id:
                    self._calls[call_id] = call
        elif kind == "tool.execution_complete":
            self.state["tool_completion_count"] += 1
            call_id = data.get("toolCallId")
            if isinstance(call_id, str) and (call := self._calls.pop(call_id, None)) is not None:
                call.update(_completion(data))
            elif _al_tool(data):
                self.state["unmatched_al_completion_count"] += 1
        elif kind == "session.mcp_servers_loaded":
            servers = data.get("servers")
            if isinstance(servers, list):
                for server in servers:
                    if isinstance(server, dict) and server.get("name") == "altool":
                        self._server_status(server.get("status"))
                        self._server_error(server.get("error"))
        elif kind == "session.mcp_server_status_changed" and data.get("serverName") == "altool":
            self._server_status(data.get("status"))
            self._server_error(data.get("error"))
        elif kind == "session.tools_updated":
            # Verified 1.0.80/1.0.86 schemas contain only a model ID, NOT resolved tool names.
            self.state["tools_updated_event_observed"] = True
        elif kind == "session.error":
            error_type = data.get("errorType")
            self.state["stop"]["session_errors"].append(error_type if isinstance(error_type, str) and error_type in _ERROR_TYPES else "unclassified")
            self.state["stop"].setdefault("reported_error_markers", []).extend(_error_markers(data.get("message")))
        elif kind == "session.shutdown":
            shutdown_type = data.get("shutdownType")
            self.state["stop"]["shutdown_event"] = shutdown_type if shutdown_type in ("routine", "error") else "unknown"
        elif kind == "result":
            exit_code = event.get("exitCode")
            self.state["stop"]["result_event"] = "observed"
            self.state["stop"]["result_exit"] = "success" if type(exit_code) is int and exit_code == 0 else "failure" if type(exit_code) is int else "unknown"
        else:
            return
        self.save()

    def _server_status(self, status: object) -> None:
        statuses = self.state["server_status_observations"]
        safe_status = status if isinstance(status, str) and status in _SERVER_STATUSES else "unknown"
        if not statuses or statuses[-1] != safe_status:
            statuses.append(safe_status)

    def _server_error(self, error: object) -> None:
        self.state["server_error_markers"] = sorted(set(self.state["server_error_markers"]) | set(_error_markers(error)))

    def run(self, command: Sequence[str], cwd: Path, env: Mapping[str, str] | None, timeout: float) -> str:
        self.state["stream"] = "observing"
        self.state["stop"]["process"] = "running"
        self.save()
        lines: list[str] = []
        process: DiagnosticProcess | None = None
        deadline = time.monotonic() + timeout
        try:
            with DiagnosticProcess(command, cwd, env) as process:
                for line in process.lines(deadline):
                    lines.append(line)
                    self.observe_line(line)
                return_code = process.wait(deadline)
                self.state["stream"] = "eof"
                self.state["stop"]["process"] = "exited_zero" if return_code == 0 else "exited_nonzero"
                if return_code:
                    raise subprocess.CalledProcessError(return_code, "copilot")
            return "".join(lines)
        except subprocess.TimeoutExpired:
            self.state["stream"] = "partial"
            self.state["stop"]["process"] = "timeout"
            raise subprocess.TimeoutExpired("copilot", timeout) from None
        except (OSError, DiagnosticReadError):
            self.state["stream"] = "partial"
            self.state["stop"]["process"] = "startup_or_io_error"
            raise DiagnosticReadError("Copilot startup or diagnostic I/O failed; see safe diagnostics") from None
        finally:
            self.state["stop"]["cleanup"] = "complete" if process is not None and process.cleanup_complete else "unavailable"
            self.save()
