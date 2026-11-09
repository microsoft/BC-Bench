from dataclasses import dataclass
from pathlib import Path

from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.exceptions import AgentError


@dataclass(frozen=True)
class CopilotOptions:
    allow_all_tools: bool = False
    custom_instructions: bool = False
    log_dir: Path | None = None
    mcp_config_json: str | None = None
    plugin_dirs: tuple[Path, ...] = ()
    granted_dirs: tuple[Path, ...] = ()
    custom_agent: str | None = None
    # None leaves the supplied environment setting unchanged.
    workspace_mcp: bool | None = None
    extra_args: tuple[str, ...] = ()


class CopilotProcessError(AgentError):
    def __init__(self, message: str, stdout: str | bytes | None = None, stderr: str | bytes | None = None, returncode: int | None = None) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(message)


class CopilotTimeoutError(CopilotProcessError):
    def __init__(self, timeout: int, stdout: str | bytes | None = None, stderr: str | bytes | None = None) -> None:
        self.timeout = timeout
        self.metrics = AgentMetrics(execution_time=timeout)
        super().__init__(f"Copilot CLI timed out after {timeout} seconds", stdout=stdout, stderr=stderr)
