from __future__ import annotations

import json
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

from bcbench.agent.shared.contained_process import (
    ContainedProcessRequest,
    ContainedProcessResult,
    _protect_temp_directory,
    run_contained_process,
)
from bcbench.agent.shared.env import agent_subprocess_env


class AlMcpBridgeError(RuntimeError):
    pass


class AlMcpBridge:
    def __init__(self, server: dict[str, Any], cwd: Path, *, timeout_seconds: int) -> None:
        self._server = StdioServerParameters.model_validate({**server, "cwd": str(cwd)})
        self._cwd = cwd
        self._timeout = timeout_seconds
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._root: Path | None = None
        self._thread: threading.Thread | None = None
        self._result: ContainedProcessResult | None = None
        self._error: BaseException | None = None
        self._stopped = False
        self.url = ""

    def start(self) -> AlMcpBridge:
        if self._thread is not None or self._stopped:
            raise AlMcpBridgeError("AL MCP bridge cannot be started twice")
        self._temporary = tempfile.TemporaryDirectory(prefix="bcbench-al-mcp-")
        self._root = Path(self._temporary.name)
        try:
            _protect_temp_directory(self._root)
            config_path = self._root / "server.json"
            config_path.write_text(
                json.dumps({"server": self._server.model_dump(mode="json"), "token": secrets.token_urlsafe(32), "timeout": self._timeout}),
                encoding="utf-8",
            )
            request = ContainedProcessRequest(
                command=(sys.executable, "-m", "bcbench.agent.shared.al_mcp_bridge_worker", str(config_path)),
                cwd=self._cwd,
                env=agent_subprocess_env(allowlist=True),
                timeout_seconds=self._timeout,
                stop_path=self._root / "terminate",
            )

            def run() -> None:
                try:
                    self._result = run_contained_process(request)
                except BaseException as error:  # noqa: BLE001 - transfer failure to the owning thread without logging secrets
                    self._error = error

            self._thread = threading.Thread(target=run, name="al-mcp-bridge")
            self._thread.start()
            ready = self._root / "ready.json"
            self._wait_for_startup(self._root / "ready")
            self.url = json.loads(ready.read_text(encoding="utf-8"))["url"]
        except BaseException:
            self.stop()
            raise
        return self

    def _wait_for_startup(self, ready: Path) -> None:
        deadline = time.monotonic() + 30
        while not ready.exists():
            if self._thread is None or not self._thread.is_alive() or time.monotonic() >= deadline:
                raise AlMcpBridgeError("AL MCP bridge transport failed during startup")
            time.sleep(0.02)

    def stop(self) -> None:
        if self._stopped:
            return
        if self._root is not None and self._thread is not None:
            (self._root / "shutdown").touch()
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                (self._root / "terminate").touch()
                self._thread.join(timeout=10)
            if self._thread.is_alive():
                raise AlMcpBridgeError("AL MCP bridge process termination could not be verified")
        self._stopped = True
        failure = self._root / "failure.json" if self._root else None
        diagnostic = failure.read_text(encoding="utf-8") if failure is not None and failure.exists() else ""
        state = self._root / "state.txt" if self._root else None
        if state is not None and state.exists():
            diagnostic += state.read_text(encoding="utf-8")
        if self._temporary is not None:
            self._temporary.cleanup()
        if self._error is not None or (self._result is not None and self._result.returncode != 0):
            raise AlMcpBridgeError(f"AL MCP bridge transport or process containment failed: {diagnostic}") from None
