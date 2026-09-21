import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, TypedDict, cast

from bcbench.config import get_config

if TYPE_CHECKING:
    from bcbench.agent.shared.managed_clients import ManagedAgentClients

__all__ = [
    "AgentExecutionPolicy",
    "ContainedProcessInfrastructureError",
    "ContainedProcessRequest",
    "ContainedProcessResult",
    "WindowsIdentity",
    "run_contained_process",
    "should_log_transcript",
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
    python_executable: Path | None = None
    worker_path: Path | None = None
    worker_sha256: str | None = None
    environment_overrides: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    managed_clients: "ManagedAgentClients | None" = field(default=None, repr=False, compare=False)
    plugin_root: Path | None = None

    def __post_init__(self) -> None:
        overrides = dict(self.environment_overrides)
        if not all(isinstance(key, str) and key for key in overrides):
            raise TypeError("Agent environment override names must be non-empty strings")
        if not all(isinstance(value, str) for value in overrides.values()):
            raise TypeError("Agent environment override values must be strings")
        object.__setattr__(self, "environment_overrides", MappingProxyType(overrides))


def should_log_transcript(execution_policy: AgentExecutionPolicy | None) -> bool:
    return execution_policy is None or not (execution_policy.contain_process_tree and execution_policy.allowlist_environment)


@dataclass(frozen=True)
class ContainedProcessRequest:
    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    timeout_seconds: int
    identity: WindowsIdentity | None = None
    python_executable: Path | None = None
    worker_path: Path | None = None
    worker_sha256: str | None = None
    stop_path: Path | None = None
    parent_environment_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.parent_environment_keys and self.identity is not None:
            raise ValueError("Restricted workers cannot inherit evaluator environment")
        names = tuple(name.upper() for name in self.parent_environment_keys)
        if len(set(names)) != len(names) or any(not name or "=" in name or "\0" in name for name in names):
            raise ValueError("Invalid parent environment keys")
        if set(names).intersection(name.upper() for name in self.env):
            raise ValueError("Parent environment keys must not duplicate serialized environment")
        object.__setattr__(self, "parent_environment_keys", names)


@dataclass(frozen=True)
class ContainedProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ContainedProcessInfrastructureError(RuntimeError):
    def __init__(
        self,
        watchdog_timeout_seconds: int | None,
        *,
        child_stdout: str,
        child_stderr: str,
        wrapper_stdout: str,
        wrapper_stderr: str,
        wrapper_returncode: int | None = None,
        reason: str | None = None,
    ) -> None:
        if reason is not None:
            message = reason
        elif wrapper_returncode is None:
            message = f"Contained process wrapper exceeded its {watchdog_timeout_seconds}-second watchdog"
        else:
            message = f"Contained process wrapper exited with status {wrapper_returncode}"
        super().__init__(message)
        self.reason = reason
        self.watchdog_timeout_seconds = watchdog_timeout_seconds
        self.wrapper_returncode = wrapper_returncode
        self.child_stdout = child_stdout
        self.child_stderr = child_stderr
        self.captured_stdout = child_stdout
        self.captured_stderr = child_stderr
        self.wrapper_stdout = wrapper_stdout
        self.wrapper_output = wrapper_stdout
        self.wrapper_stderr = wrapper_stderr
        self.output = wrapper_stdout
        self.stderr = wrapper_stderr

    @classmethod
    def from_called_process_error(
        cls,
        error: subprocess.CalledProcessError,
        *,
        child_stdout: str = "",
        child_stderr: str = "",
    ) -> "ContainedProcessInfrastructureError":
        return cls(
            None,
            child_stdout=child_stdout,
            child_stderr=child_stderr,
            wrapper_stdout=_normalized_subprocess_output(error.stdout),
            wrapper_stderr=_normalized_subprocess_output(error.stderr),
            wrapper_returncode=error.returncode,
        )


class _WrapperResult(TypedDict):
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


_WORKER_STARTUP_TIMEOUT_SECONDS = 30
_WRAPPER_SHUTDOWN_GRACE_SECONDS = 10
_MAX_WINDOWS_RETURN_CODE = 0xFFFFFFFF
_WRAPPER_RESULT_FIELDS = {"returncode", "stdout", "stderr", "timed_out"}


def _write_request(path: Path, request: ContainedProcessRequest) -> None:
    payload = {
        "command": list(request.command),
        "cwd": str(request.cwd),
        "env": request.env,
        "timeout_seconds": request.timeout_seconds,
        "identity": asdict(request.identity) if request.identity is not None else None,
    }
    if request.stop_path is not None:
        payload["stop_path"] = str(request.stop_path)
    if request.parent_environment_keys:
        payload["parent_environment_keys"] = list(request.parent_environment_keys)
    with path.open("x", encoding="utf-8") as request_file:
        json.dump(payload, request_file, separators=(",", ":"))


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _normalized_subprocess_output(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return _normalize_newlines(output or "")


def _parse_wrapper_result(wrapper_stdout: str) -> _WrapperResult:
    payload = json.loads(wrapper_stdout)
    if not isinstance(payload, dict):
        raise TypeError("Contained process wrapper response must be a JSON object")

    fields = set(payload)
    if fields != _WRAPPER_RESULT_FIELDS:
        missing = sorted(_WRAPPER_RESULT_FIELDS - fields)
        extra = sorted(fields - _WRAPPER_RESULT_FIELDS)
        raise ValueError(f"Contained process wrapper response fields are invalid: missing={missing}, extra={extra}")

    timed_out = payload["timed_out"]
    if type(timed_out) is not bool:
        raise TypeError("Contained process wrapper response timed_out must be a boolean")

    stdout = payload["stdout"]
    stderr = payload["stderr"]
    if not isinstance(stdout, str):
        raise TypeError("Contained process wrapper response stdout must be a string")
    if not isinstance(stderr, str):
        raise TypeError("Contained process wrapper response stderr must be a string")

    returncode = payload["returncode"]
    if timed_out:
        if returncode is not None:
            raise ValueError("Contained process wrapper response returncode must be null when timed_out is true")
    else:
        if returncode is None:
            raise ValueError("Contained process wrapper response returncode cannot be null when timed_out is false")
        if type(returncode) is not int:
            raise TypeError("Contained process wrapper response returncode must be an integer when timed_out is false")
        if not 0 <= returncode <= _MAX_WINDOWS_RETURN_CODE:
            raise ValueError("Contained process wrapper response returncode must be an unsigned 32-bit integer")

    return cast(_WrapperResult, payload)


def _current_windows_user_sid() -> str:
    if sys.platform != "win32":
        raise OSError("Windows identity APIs are unavailable on this platform")
    from ctypes import WinDLL, WinError, get_last_error, wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    advapi32 = WinDLL("advapi32", use_last_error=True)
    kernel32 = WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = ()
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise WinError(get_last_error())

    try:
        required_size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required_size))
        buffer = ctypes.create_string_buffer(required_size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required_size, ctypes.byref(required_size)):
            raise WinError(get_last_error())

        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_string_pointer = ctypes.c_void_p()
        if not advapi32.ConvertSidToStringSidW(token_user.user.sid, ctypes.byref(sid_string_pointer)):
            raise WinError(get_last_error())
        try:
            return ctypes.wstring_at(sid_string_pointer)
        finally:
            kernel32.LocalFree(sid_string_pointer)
    finally:
        kernel32.CloseHandle(token)


def _protect_temp_directory(path: Path) -> None:
    if sys.platform != "win32":
        raise OSError("Windows ACL APIs are unavailable on this platform")
    from ctypes import WinDLL, WinError, get_last_error, wintypes

    advapi32 = WinDLL("advapi32", use_last_error=True)
    kernel32 = WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    )
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.SetFileSecurityW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p)
    advapi32.SetFileSecurityW.restype = wintypes.BOOL
    security_descriptor = ctypes.c_void_p()
    sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;{_current_windows_user_sid()})"
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl,
        1,
        ctypes.byref(security_descriptor),
        None,
    ):
        raise WinError(get_last_error())
    try:
        if not advapi32.SetFileSecurityW(str(path), 0x80000004, security_descriptor):
            raise WinError(get_last_error())
    finally:
        kernel32.LocalFree(security_descriptor)


def _powershell_executable() -> str:
    executable = shutil.which("pwsh")
    if executable is None:
        raise FileNotFoundError("PowerShell 7 executable 'pwsh' was not found")
    return executable


def _worker_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _resolve_worker_launch(request: ContainedProcessRequest) -> tuple[Path, Path, str]:
    source_worker_path = Path(__file__).with_name("contained_process_worker.py").resolve()
    worker_path = (request.worker_path or source_worker_path).resolve()
    python_executable = Path(request.python_executable or getattr(sys, "_base_executable", sys.executable)).resolve()
    if not source_worker_path.is_file():
        raise FileNotFoundError(source_worker_path)
    if not worker_path.is_file():
        raise FileNotFoundError(worker_path)
    if not python_executable.is_file():
        raise FileNotFoundError(python_executable)

    source_digest = _worker_digest(source_worker_path)
    expected_digest = (request.worker_sha256 or source_digest).lower()
    if expected_digest != source_digest:
        raise ContainedProcessInfrastructureError(
            None,
            child_stdout="",
            child_stderr="",
            wrapper_stdout="",
            wrapper_stderr="",
            reason="Contained process worker hash does not match the evaluator source worker",
        )
    if _worker_digest(worker_path) != expected_digest:
        raise ContainedProcessInfrastructureError(
            None,
            child_stdout="",
            child_stderr="",
            wrapper_stdout="",
            wrapper_stderr="",
            reason="Contained process staged worker hash does not match the evaluator source worker",
        )
    return python_executable, worker_path, expected_digest


@contextmanager
def _contained_process_directory() -> Iterator[Path]:
    temporary = tempfile.TemporaryDirectory(prefix="bcbench-contained-")
    failure: BaseException | None = None
    try:
        yield Path(temporary.name)
    except (ContainedProcessInfrastructureError, KeyboardInterrupt) as error:
        failure = error
        raise
    finally:
        try:
            temporary.cleanup()
        except OSError as cleanup_error:
            if failure is None:
                raise
            failure.add_note(f"Contained process temporary cleanup also failed ({type(cleanup_error).__name__}): {temporary.name}")


def run_contained_process(request: ContainedProcessRequest) -> ContainedProcessResult:
    script_path = get_config().paths.ps_script_path / "Invoke-ContainedProcess.ps1"
    if not script_path.is_file():
        raise FileNotFoundError(script_path)

    python_executable, worker_path, worker_sha256 = _resolve_worker_launch(request)
    with _contained_process_directory() as temp_path:
        _protect_temp_directory(temp_path)
        private_path = temp_path / "private"
        shared_path = temp_path / "shared"
        private_path.mkdir()
        shared_path.mkdir()

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
            str(python_executable),
            "-WorkerPath",
            str(worker_path),
            "-ExpectedWorkerSha256",
            worker_sha256,
            "-WorkerStartupTimeoutSeconds",
            str(_WORKER_STARTUP_TIMEOUT_SECONDS),
        ]
        watchdog_timeout_seconds = request.timeout_seconds + _WORKER_STARTUP_TIMEOUT_SECONDS + _WRAPPER_SHUTDOWN_GRACE_SECONDS
        try:
            completed = subprocess.run(
                wrapper_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
                timeout=watchdog_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            # Only the wrapper's valid result proves job drainage; failure-path captures may still be held open.
            raise ContainedProcessInfrastructureError(
                watchdog_timeout_seconds,
                child_stdout="",
                child_stderr="",
                wrapper_stdout=_normalized_subprocess_output(exc.output),
                wrapper_stderr=_normalized_subprocess_output(exc.stderr),
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise ContainedProcessInfrastructureError.from_called_process_error(
                exc,
            ) from exc

        try:
            payload = _parse_wrapper_result(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise ContainedProcessInfrastructureError(
                None,
                child_stdout="",
                child_stderr="",
                wrapper_stdout=_normalized_subprocess_output(completed.stdout),
                wrapper_stderr=_normalized_subprocess_output(completed.stderr),
                wrapper_returncode=completed.returncode,
                reason=f"Contained process wrapper returned an invalid response: {exc}",
            ) from exc
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
