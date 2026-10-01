import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench.agent.shared.diagnostic_process import DiagnosticProcess, DiagnosticReadError
from bcbench.diagnostics.mcp_diagnostics import SafeDiagnosticSnapshot


class CopilotDiagnostics:
    def __init__(self, snapshot: SafeDiagnosticSnapshot) -> None:
        self.snapshot = snapshot
        self.state: dict[str, str | int | None] = {"process": "not_started", "exit_code": None, "cleanup": "unobserved"}
        snapshot.document["agent"] = self.state
        self.save()

    def save(self) -> None:
        self.snapshot.save()

    def run(self, command: Sequence[str], cwd: Path, env: Mapping[str, str] | None, timeout: float) -> str:
        self.state["process"] = "running"
        self.save()
        process: DiagnosticProcess | None = None
        deadline = time.monotonic() + timeout
        try:
            with DiagnosticProcess(command, cwd, env) as process:
                stdout = "".join(process.lines(deadline))
                return_code = process.wait(deadline)
                self.state.update(process="exited", exit_code=return_code)
                if return_code:
                    raise subprocess.CalledProcessError(return_code, "copilot")
        except subprocess.TimeoutExpired:
            self.state["process"] = "timeout"
            raise subprocess.TimeoutExpired("copilot", timeout) from None
        except (OSError, DiagnosticReadError):
            self.state["process"] = "startup_or_io_error"
            raise DiagnosticReadError("Copilot startup or diagnostic I/O failed; see safe diagnostics") from None
        else:
            return stdout
        finally:
            self.state["cleanup"] = "complete" if process is not None and process.cleanup_complete else "unavailable"
            self.save()
