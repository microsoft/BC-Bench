from collections.abc import Callable
from pathlib import Path
from typing import Any

from bcbench.agent.shared.al_mcp_bridge import AlMcpBridge
from bcbench.config import get_config


class ManagedAgentClients:
    def __init__(self) -> None:
        self._stoppers: list[Callable[[], None]] = []
        self._closed = False
        self._failure: RuntimeError | None = None

    def register(self, stop: Callable[[], None]) -> None:
        if self._closed:
            raise RuntimeError("Agent client lifetime is closed")
        self._stoppers.append(stop)

    def start_al_mcp(self, server: dict[str, Any], cwd: Path) -> str:
        bridge = AlMcpBridge(server, cwd, timeout_seconds=get_config().timeout.agent_execution + 60)
        self.register(bridge.stop)
        return bridge.start().url

    def stop(self) -> None:
        if self._failure is not None:
            raise self._failure
        if self._closed:
            return
        self._closed = True
        errors = []
        for stop in reversed(self._stoppers):
            try:
                stop()
            except Exception as error:  # noqa: BLE001 - attempt every owned client before failing the isolation barrier
                errors.append(type(error).__name__)
        if errors:
            self._failure = RuntimeError(f"Agent client shutdown/transport verification failed: {', '.join(errors)}")
            raise self._failure
