import json
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict, cast

from bcbench.config import get_config

__all__ = [
    "AgentExecutionPolicy",
    "ContainedProcessRequest",
    "ContainedProcessResult",
    "WindowsIdentity",
    "run_contained_process",
]


@dataclass(frozen=True)
class WindowsIdentity:
    username: str
    password: str
    domain: str = "."


@dataclass(frozen=True)
class AgentExecutionPolicy:
    contain_process_tree: bool = False
    restricted_identity: WindowsIdentity | None = None
    allowlist_environment: bool = False


@dataclass(frozen=True)
class ContainedProcessRequest:
    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    timeout_seconds: int
    identity: WindowsIdentity | None = None


@dataclass(frozen=True)
class ContainedProcessResult:
    returncode: int
    stdout: str
    stderr: str


class _WrapperResult(TypedDict):
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


_WORKER_STARTUP_TIMEOUT_SECONDS = 30
_WRAPPER_SHUTDOWN_GRACE_SECONDS = 10


def _write_request(path: Path, request: ContainedProcessRequest) -> None:
    payload = {
        "command": list(request.command),
        "cwd": str(request.cwd),
        "env": request.env,
        "timeout_seconds": request.timeout_seconds,
        "identity": asdict(request.identity) if request.identity is not None else None,
    }
    with path.open("x", encoding="utf-8") as request_file:
        json.dump(payload, request_file, separators=(",", ":"))
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _read_capture(path: Path) -> str:
    return _normalize_newlines(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else ""


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _powershell_executable() -> str:
    executable = shutil.which("pwsh")
    if executable is None:
        raise FileNotFoundError("PowerShell 7 executable 'pwsh' was not found")
    return executable


def run_contained_process(request: ContainedProcessRequest) -> ContainedProcessResult:
    script_path = get_config().paths.ps_script_path / "Invoke-ContainedProcess.ps1"
    if not script_path.is_file():
        raise FileNotFoundError(script_path)

    worker_path = Path(__file__).with_name("contained_process_worker.py")
    with tempfile.TemporaryDirectory(prefix="bcbench-contained-") as temp_dir:
        temp_path = Path(temp_dir)
        private_path = temp_path / "private"
        shared_path = temp_path / "shared"
        private_path.mkdir()
        shared_path.mkdir()
        private_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

        request_path = private_path / "request.json"
        worker_request_path = shared_path / "worker-request.json"
        gate_path = shared_path / "launch.gate"
        stdout_path = shared_path / "stdout.txt"
        stderr_path = shared_path / "stderr.txt"
        _write_request(request_path, request)

        wrapper_command = [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script_path),
            "-RequestPath",
            str(request_path),
            "-WorkerRequestPath",
            str(worker_request_path),
            "-GatePath",
            str(gate_path),
            "-StdoutPath",
            str(stdout_path),
            "-StderrPath",
            str(stderr_path),
            "-PythonExecutable",
            sys.executable,
            "-WorkerPath",
            str(worker_path),
            "-WorkerStartupTimeoutSeconds",
            str(_WORKER_STARTUP_TIMEOUT_SECONDS),
        ]
        try:
            completed = subprocess.run(
                wrapper_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=request.timeout_seconds + _WORKER_STARTUP_TIMEOUT_SECONDS + _WRAPPER_SHUTDOWN_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise subprocess.TimeoutExpired(
                request.command,
                request.timeout_seconds,
                output=_read_capture(stdout_path),
                stderr=_read_capture(stderr_path),
            ) from exc

        payload = cast(_WrapperResult, json.loads(completed.stdout))
        stdout = _normalize_newlines(payload["stdout"])
        stderr = _normalize_newlines(payload["stderr"])
        if payload["timed_out"]:
            raise subprocess.TimeoutExpired(
                request.command,
                request.timeout_seconds,
                output=stdout,
                stderr=stderr,
            )
        return ContainedProcessResult(
            returncode=cast(int, payload["returncode"]),
            stdout=stdout,
            stderr=stderr,
        )
