import ctypes
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TypedDict, cast

from bcbench.config import get_config

__all__ = [
    "AgentExecutionPolicy",
    "ContainedProcessInfrastructureError",
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
    ) -> None:
        if wrapper_returncode is None:
            message = f"Contained process wrapper exceeded its {watchdog_timeout_seconds}-second watchdog"
        else:
            message = f"Contained process wrapper exited with status {wrapper_returncode}"
        super().__init__(message)
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


def _read_capture(path: Path) -> str:
    return _normalize_newlines(path.read_text(encoding="utf-8", errors="replace")) if path.exists() else ""


def _normalize_newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _normalized_subprocess_output(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        output = output.decode("utf-8", errors="replace")
    return _normalize_newlines(output or "")


def _current_windows_user_sid() -> str:
    from ctypes import wintypes

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    class TokenUser(ctypes.Structure):
        _fields_ = [("user", SidAndAttributes)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        required_size = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required_size))
        buffer = ctypes.create_string_buffer(required_size.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required_size, ctypes.byref(required_size)):
            raise ctypes.WinError(ctypes.get_last_error())

        token_user = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents
        sid_string_pointer = ctypes.c_void_p()
        if not advapi32.ConvertSidToStringSidW(token_user.user.sid, ctypes.byref(sid_string_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.wstring_at(sid_string_pointer)
        finally:
            kernel32.LocalFree(sid_string_pointer)
    finally:
        kernel32.CloseHandle(token)


def _protect_temp_directory(path: Path) -> None:
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not advapi32.SetFileSecurityW(str(path), 0x80000004, security_descriptor):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.LocalFree(security_descriptor)


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
            sys.executable,
            "-WorkerPath",
            str(worker_path),
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
            raise ContainedProcessInfrastructureError(
                watchdog_timeout_seconds,
                child_stdout=_read_capture(stdout_path),
                child_stderr=_read_capture(stderr_path),
                wrapper_stdout=_normalized_subprocess_output(exc.output),
                wrapper_stderr=_normalized_subprocess_output(exc.stderr),
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise ContainedProcessInfrastructureError.from_called_process_error(
                exc,
                child_stdout=_read_capture(stdout_path),
                child_stderr=_read_capture(stderr_path),
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
