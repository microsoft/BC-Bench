import json
import logging
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# A disclosure allowlist, not an expected/observed catalog.
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


class SafeDiagnosticSnapshot:
    def __init__(self, output_dir: Path, *, invocation_id: str | None = None, connection_id: str | None = None) -> None:
        self.invocation_id = invocation_id or uuid4().hex
        self.output_dir = output_dir.resolve()
        self.path = self.output_dir / "diagnostics" / "al-mcp.json"
        self.document: dict[str, Any] = {
            "schema_version": 2,
            "invocation_id": self.invocation_id,
        }
        if connection_id is not None:
            self.path = self.output_dir / "diagnostics" / "al-mcp-transport" / self.invocation_id / f"{connection_id}.json"
            self.document["connection_id"] = connection_id
        else:
            self.document["transport"] = {
                "source": "actual_agent_stdio",
                "status": "not_configured",
                "snapshots": str(Path("al-mcp-transport") / self.invocation_id / "*.json"),
                "model_visibility": "unknown",
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


def observe_al_connection(config_json: str | None, snapshot: SafeDiagnosticSnapshot) -> str | None:
    config = json.loads(config_json or "{}")
    server = config.get("mcpServers", {}).get("altool")
    if not isinstance(server, dict) or server.get("type") != "stdio":
        snapshot.document["transport"]["status"] = "stdio_configuration_unavailable"
        snapshot.save()
        logger.warning("AL MCP observation unavailable: stdio_configuration_unavailable")
        return config_json
    command, args = server.get("command"), server.get("args")
    if not isinstance(command, str) or not command or not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        snapshot.document["transport"]["status"] = "invalid_stdio_configuration"
        snapshot.save()
        logger.warning("AL MCP observation unavailable: invalid_stdio_configuration")
        return config_json
    server["command"] = sys.executable
    server["args"] = [
        "-u",
        str(Path(__file__).with_name("mcp_proxy.py")),
        str(snapshot.output_dir),
        snapshot.invocation_id,
        "--",
        command,
        *args,
    ]
    snapshot.document["transport"]["status"] = "configured"
    snapshot.save()
    return json.dumps(config, separators=(",", ":"))
