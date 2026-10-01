import json
import os
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

from bcbench.agent.shared.diagnostic_process import DiagnosticProcess, DiagnosticReadError
from bcbench.logger import get_logger

logger = get_logger(__name__)

# A disclosure allowlist, NOT an expected/observed catalog. Unrecognized names are counted, never copied.
AL_TOOL_NAMES = frozenset(
    {
        "al_addproject",
        "al_auth_login",
        "al_auth_logout",
        "al_build",
        "al_compile",
        "al_downloadsymbols",
        "al_getdiagnostics",
        "al_getpackagedependencies",
        "al_inspectpage",
        "al_publish",
        "al_run_tests",
        "al_searchtranslations",
        "al_symbolrelations",
        "al_symbolsearch",
        "al_writetranslation",
    }
)
TARGET_TOOLS = ("al_publish", "al_run_tests")
_DISCOVERY_ENV = frozenset({"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "DOTNET_ROOT", "DOTNET_ROOT_X64"})


class SafeDiagnosticSnapshot:
    def __init__(self, output_dir: Path) -> None:
        self.path = output_dir / "diagnostics" / "al-mcp.json"
        self.document: dict[str, Any] = {
            "schema_version": 1,
            "catalog": {
                "source": "runtime_stdio_tools_list",
                "process": "separate_read_only_discovery_before_agent",
                "configuration": "agent_command_and_args_without_server_env",
                "credentials": "not_forwarded",
                "model_visibility": "unknown",
                "status": "not_started",
                "complete": False,
                "tool_names": [],
                "name_projection": "allowlisted_names_only",
                "withheld_tool_name_count": 0,
                "target_availability": dict.fromkeys(TARGET_TOOLS, "unknown"),
            },
        }
        self._write_warning_logged = False
        self.save()

    def save(self) -> None:
        staging = self.path.with_suffix(".pending")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with staging.open("w", encoding="utf-8") as stream:
                json.dump(self.document, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            # Windows readers may briefly deny replacing an open snapshot.
            for attempt in range(5):
                try:
                    staging.replace(self.path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.01 * 2**attempt)
        except OSError:
            if not self._write_warning_logged:
                logger.warning("AL MCP diagnostic snapshot unavailable: filesystem_error")
                self._write_warning_logged = True
            with suppress(OSError):
                staging.unlink(missing_ok=True)


class _DiscoveryError(Exception):
    pass


def _send(process: DiagnosticProcess, method: str, request_id: int | None = None, params: dict | None = None) -> None:
    if method not in {"initialize", "notifications/initialized", "tools/list"}:
        raise _DiscoveryError("unsupported_method")
    message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    process.send_line(json.dumps(message))


def _discover_catalog(snapshot: SafeDiagnosticSnapshot, config_json: str | None, repo_path: Path, deadline: float) -> None:
    catalog = snapshot.document["catalog"]
    config = json.loads(config_json or "{}")
    server = config.get("mcpServers", {}).get("altool")
    if not isinstance(server, dict) or server.get("type") != "stdio":
        raise _DiscoveryError("stdio_configuration_unavailable")
    command, args = server.get("command"), server.get("args")
    if not isinstance(command, str) or not command or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise _DiscoveryError("invalid_stdio_configuration")
    # No inherited tokens, BC credentials, server env, proxy credentials, or extra AL flags.
    env = {key: value for key, value in os.environ.items() if key.upper() in _DISCOVERY_ENV}
    process = DiagnosticProcess([command, *args], repo_path, env, max_line_length=4 * 1024 * 1024, write_stdin=True)
    try:
        with process:
            catalog["status"] = "initializing"
            snapshot.save()
            request_id = 1
            _send(
                process,
                "initialize",
                request_id,
                {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "bcbench-diagnostics", "version": "1"}},
            )
            seen_cursors: set[str] = set()
            observed_names: set[str] = set()
            for line in process.lines(deadline):
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    # MCP stdio is newline-delimited JSON; startup chatter is never copied to artifacts.
                    catalog["ignored_stdout_lines"] += 1
                    snapshot.save()
                    if line.lower().startswith("content-length:"):
                        raise _DiscoveryError("unsupported_stdout_framing") from None
                    if catalog["ignored_stdout_lines"] > 100:
                        raise _DiscoveryError("invalid_stdout_framing") from None
                    continue
                if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                    raise _DiscoveryError("invalid_protocol_response")
                if type(response.get("id")) is not int or response["id"] != request_id:
                    continue
                if "error" in response:
                    raise _DiscoveryError("rpc_error")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise _DiscoveryError("invalid_result")
                if request_id == 1:
                    if result.get("protocolVersion") not in ("2024-11-05", "2025-03-26", "2025-06-18"):
                        raise _DiscoveryError("unsupported_protocol_version")
                    capabilities = result.get("capabilities")
                    if not isinstance(capabilities, dict) or not isinstance(capabilities.get("tools"), dict):
                        raise _DiscoveryError("tools_capability_unavailable")
                    catalog["status"] = "listing"
                    snapshot.save()
                    _send(process, "notifications/initialized")
                    request_id += 1
                    _send(process, "tools/list", request_id)
                    continue
                tools = result.get("tools")
                if not isinstance(tools, list) or any(not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"] for tool in tools):
                    raise _DiscoveryError("invalid_tools_list")
                observed_names.update(tool["name"] for tool in tools)
                catalog["pages_observed"] += 1
                cursor = result.get("nextCursor")
                complete = cursor is None
                catalog.update(
                    tool_names=sorted(observed_names & AL_TOOL_NAMES),
                    withheld_tool_name_count=len(observed_names - AL_TOOL_NAMES),
                    total_tool_count=len(observed_names),
                    complete=complete,
                    status="observed" if complete else "listing",
                    target_availability={name: "present" if name in observed_names else "absent" if complete else "unknown" for name in TARGET_TOOLS},
                )
                snapshot.save()
                if complete:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in seen_cursors or catalog["pages_observed"] >= 50:
                    raise _DiscoveryError("invalid_pagination")
                seen_cursors.add(cursor)
                request_id += 1
                _send(process, "tools/list", request_id, {"cursor": cursor})
            if not catalog["complete"]:
                raise _DiscoveryError("process_exit_before_catalog")
    finally:
        catalog["cleanup"] = "complete" if process.cleanup_complete else "unavailable"


def observe_al_catalog(snapshot: SafeDiagnosticSnapshot, config_json: str | None, repo_path: Path, *, timeout: float = 30) -> None:
    catalog = snapshot.document["catalog"]
    start = time.monotonic()
    catalog.update(status="starting", timeout_seconds=timeout, ignored_stdout_lines=0, pages_observed=0, cleanup="unavailable")
    snapshot.save()
    try:
        _discover_catalog(snapshot, config_json, repo_path, start + timeout)
    except subprocess.TimeoutExpired:
        catalog.update(status="failed", error_category="timeout")
    except _DiscoveryError as error:
        catalog.update(status="failed", error_category=str(error))
    except DiagnosticReadError:
        catalog.update(status="failed", error_category="protocol_io_error")
    except (OSError, ValueError, TypeError, AttributeError, RecursionError):
        catalog.update(status="failed", error_category="startup_or_io_error")
    finally:
        catalog["elapsed_seconds"] = round(time.monotonic() - start, 3)
        snapshot.save()
    logger.info(
        "AL MCP runtime catalog (%s; separate process; model visibility unknown): tools=%s; withheld_names=%s; al_publish=%s, al_run_tests=%s",
        catalog["status"],
        catalog["tool_names"],
        catalog["withheld_tool_name_count"],
        catalog["target_availability"]["al_publish"],
        catalog["target_availability"]["al_run_tests"],
    )
