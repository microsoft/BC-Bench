import ctypes
import json
import os
import secrets
import shutil
import string
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bcbench.agent.shared import contained_process as contained_process_module
from bcbench.agent.shared.contained_process import (
    AgentExecutionPolicy,
    ContainedProcessInfrastructureError,
    ContainedProcessRequest,
    ContainedProcessResult,
    WindowsIdentity,
    run_contained_process,
)
from bcbench.agent.shared.env import agent_subprocess_env

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects are required")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_HIGH_BIT_EXIT_CODES = (0x80000000, 0xFFFFFFFF)
_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "Invoke-ContainedProcess.ps1"
_WORKER_PATH = Path(__file__).parents[1] / "src" / "bcbench" / "agent" / "shared" / "contained_process_worker.py"


def test_wrapper_launches_worker_file_from_requested_workspace() -> None:
    source = _SCRIPT_PATH.read_text(encoding="utf-8")

    assert "$workerArguments = @(\n        $WorkerPath," in source
    assert "[string]$request.cwd" in source
    assert "(Split-Path -Parent $WorkerPath)" not in source


def _request(
    tmp_path: Path,
    code: str,
    *,
    timeout_seconds: int = 10,
    env: dict[str, str] | None = None,
) -> ContainedProcessRequest:
    return ContainedProcessRequest(
        command=(sys.executable, "-c", code),
        cwd=tmp_path,
        env=env or agent_subprocess_env(allowlist=True),
        timeout_seconds=timeout_seconds,
    )


def _exit_process_command(returncode: int) -> tuple[str, ...]:
    code = """
import ctypes
import sys

kernel32 = ctypes.WinDLL("kernel32")
kernel32.ExitProcess.argtypes = (ctypes.c_uint32,)
kernel32.ExitProcess.restype = None
kernel32.ExitProcess(int(sys.argv[1], 0))
"""
    return (sys.executable, "-c", code, hex(returncode))


def _pid_is_running(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.GetExitCodeProcess.restype = ctypes.c_bool
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _wait_until_stopped(pid: int, timeout_seconds: float = 5) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_is_running(pid):
            return True
        time.sleep(0.05)
    return not _pid_is_running(pid)


def _run_command_leaving_sleeping_descendants(
    tmp_path: Path,
    returncode: int,
) -> tuple[ContainedProcessResult, int, int]:
    child_pid_path = tmp_path / "child.pid"
    grandchild_pid_path = tmp_path / "grandchild.pid"
    grandchild_code = """
import os
import sys
import time
from pathlib import Path

pid_path = Path(sys.argv[1])
pending_pid_path = pid_path.with_suffix(".tmp")
pending_pid_path.write_text(str(os.getpid()), encoding="utf-8")
pending_pid_path.replace(pid_path)
time.sleep(60)
"""
    child_code = """
import os
import subprocess
import sys
import time
from pathlib import Path

pid_path = Path(sys.argv[1])
pending_pid_path = pid_path.with_suffix(".tmp")
pending_pid_path.write_text(str(os.getpid()), encoding="utf-8")
pending_pid_path.replace(pid_path)
subprocess.Popen([sys.executable, "-c", sys.argv[3], sys.argv[2]])
time.sleep(60)
"""
    command_code = """
import subprocess
import sys
import time
from pathlib import Path

child_pid_path = Path(sys.argv[1])
grandchild_pid_path = Path(sys.argv[2])
subprocess.Popen(
    [sys.executable, "-c", sys.argv[4], sys.argv[1], sys.argv[2], sys.argv[5]]
)
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    if child_pid_path.exists() and grandchild_pid_path.exists():
        raise SystemExit(int(sys.argv[3]))
    time.sleep(0.01)
raise RuntimeError("descendant PIDs were not recorded")
"""
    result = run_contained_process(
        ContainedProcessRequest(
            command=(
                sys.executable,
                "-c",
                command_code,
                str(child_pid_path),
                str(grandchild_pid_path),
                str(returncode),
                child_code,
                grandchild_code,
            ),
            cwd=tmp_path,
            env=agent_subprocess_env(allowlist=True),
            timeout_seconds=10,
        )
    )
    return (
        result,
        int(child_pid_path.read_text(encoding="utf-8")),
        int(grandchild_pid_path.read_text(encoding="utf-8")),
    )


def _wrapper_command(
    tmp_path: Path,
    *,
    worker_path: Path = _WORKER_PATH,
    extra_arguments: tuple[str, ...] = (),
) -> list[str]:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "command": [sys.executable, "-c", "print('worker command')"],
                "cwd": str(tmp_path),
                "env": agent_subprocess_env(allowlist=True),
                "timeout_seconds": 10,
                "identity": None,
            }
        ),
        encoding="utf-8",
    )
    return [
        shutil.which("pwsh") or "pwsh",
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-File",
        str(_SCRIPT_PATH),
        "-RequestPath",
        str(request_path),
        "-WorkerRequestPath",
        str(tmp_path / "worker-request.json"),
        "-GatePath",
        str(tmp_path / "launch.gate"),
        "-StdoutPath",
        str(tmp_path / "stdout.txt"),
        "-StderrPath",
        str(tmp_path / "stderr.txt"),
        "-PythonExecutable",
        sys.executable,
        "-WorkerPath",
        str(worker_path),
        "-WorkerStartupTimeoutSeconds",
        "5",
        *extra_arguments,
    ]


def _lifecycle_events(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _created_pid(events: list[str]) -> int:
    return int(next(event.removeprefix("Created:") for event in events if event.startswith("Created:")))


def _is_elevated() -> bool:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def _can_open_named_pipe(path: str) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    )
    kernel32.CreateFileW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_bool
    handle = kernel32.CreateFileW(path, 0xC0000000, 0, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        return False
    kernel32.CloseHandle(handle)
    return True


def _random_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return f"Aa1!{''.join(secrets.choice(alphabet) for _ in range(28))}"


def _run_powershell(script: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("pwsh") or "pwsh", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
        env={**os.environ, **env},
    )


def test_public_models_are_immutable():
    identity = WindowsIdentity("runner", "secret")
    policy = AgentExecutionPolicy()
    request = ContainedProcessRequest(("agent", "--run"), Path.cwd(), {"FLAG": "on"}, 30, identity)
    result = ContainedProcessResult(0, "stdout", "stderr")

    assert identity.domain == "."
    assert policy == AgentExecutionPolicy(contain_process_tree=False, restricted_identity=None, allowlist_environment=False)
    assert request.identity is identity
    assert result.returncode == 0
    with pytest.raises(AttributeError):
        identity.username = "other"


def test_powershell_uses_checked_job_object_wrapper_methods():
    source = _SCRIPT_PATH.read_text(encoding="utf-8")
    powershell_source = source.split("'@", maxsplit=1)[1]

    assert "public static BCBenchSafeJobHandle CreateKillOnCloseJob()" in source
    assert "CreateProcessW" in source
    assert "CreateProcessWithLogonW" in source
    assert "CREATE_SUSPENDED" in source
    assert "CREATE_UNICODE_ENVIRONMENT" in source
    assert "SafeProcessHandle" in source
    assert "SafeWaitHandle" in source
    assert "public static void AssignProcess(" in source
    assert "public static void ResumePrimaryThread(" in source
    assert "public static void TerminateJob(" in source
    assert "public static void TerminateProcess(" in source
    assert "private static extern IntPtr CreateJobObject(" in source
    assert "private static extern bool SetInformationJobObject(" in source
    assert "private static extern bool AssignProcessToJobObject(" in source
    assert "private static extern bool TerminateJobObject(" in source
    for operation in (
        "CreateJobObject",
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "TerminateJobObject",
        "CreateProcessW",
        "CreateProcessWithLogonW",
        "ResumeThread",
        "TerminateProcess",
    ):
        assert f'"{operation}"' in source
    assert 'operation + " failed"' in source
    assert "$job = [BCBenchJobObject]::CreateKillOnCloseJob()" in powershell_source
    assert "[BCBenchJobObject]::AssignProcess($job, $worker.ProcessHandle)" in powershell_source
    assert "[BCBenchJobObject]::ResumePrimaryThread($worker)" in powershell_source
    assert "[BCBenchJobObject]::TerminateJob($job, 1)" in powershell_source
    assert "[Diagnostics.Process]::new()" not in powershell_source
    assert "Process.Start" not in powershell_source
    assert "[BCBenchJobObject]::CreateJobObject(" not in powershell_source
    assert "[BCBenchJobObject]::SetInformationJobObject(" not in powershell_source
    assert "[BCBenchJobObject]::AssignProcessToJobObject(" not in powershell_source
    assert "[BCBenchJobObject]::TerminateJobObject(" not in powershell_source


def test_assign_resume_and_gate_creation_are_strictly_ordered(tmp_path):
    trace_path = tmp_path / "lifecycle.txt"
    completed = subprocess.run(
        _wrapper_command(tmp_path, extra_arguments=("-TestLifecycleTracePath", str(trace_path))),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    events = _lifecycle_events(trace_path)
    assert [event.split(":", maxsplit=1)[0] for event in events] == ["Created", "Assigned", "Resumed", "GateCreated"]
    assert (tmp_path / "launch.gate").is_file()


def test_assignment_failure_terminates_suspended_worker_without_resuming(tmp_path):
    marker_path = tmp_path / "worker-started.txt"
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        f"from pathlib import Path\nimport time\nPath({str(marker_path)!r}).touch()\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    trace_path = tmp_path / "lifecycle.txt"

    completed = subprocess.run(
        _wrapper_command(
            tmp_path,
            worker_path=worker_path,
            extra_arguments=(
                "-TestLifecycleTracePath",
                str(trace_path),
                "-TestFailAssignProcess",
            ),
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
        check=False,
    )

    events = _lifecycle_events(trace_path)
    pid = _created_pid(events)
    assert completed.returncode != 0
    assert "Assigned" not in events
    assert "Resumed" not in events
    assert "GateCreated" not in events
    assert not marker_path.exists()
    assert not (tmp_path / "launch.gate").exists()
    assert _wait_until_stopped(pid)


def test_wrapper_termination_closes_job_and_kills_resumed_worker(tmp_path):
    worker_pid_path = tmp_path / "worker.pid"
    worker_path = tmp_path / "worker.py"
    worker_path.write_text(
        f"from pathlib import Path\nimport os, time\nPath({str(worker_pid_path)!r}).write_text(str(os.getpid()), encoding='utf-8')\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    trace_path = tmp_path / "lifecycle.txt"
    wrapper = subprocess.Popen(
        _wrapper_command(
            tmp_path,
            worker_path=worker_path,
            extra_arguments=(
                "-TestLifecycleTracePath",
                str(trace_path),
                "-TestPauseAfterResumeMilliseconds",
                "30000",
            ),
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and (not worker_pid_path.exists() or "Resumed" not in _lifecycle_events(trace_path)):
            time.sleep(0.05)
        assert worker_pid_path.exists()
        assert "Resumed" in _lifecycle_events(trace_path)
        assert not (tmp_path / "launch.gate").exists()

        worker_pid = int(worker_pid_path.read_text(encoding="utf-8"))
        wrapper.kill()
        wrapper.wait(timeout=5)

        assert _wait_until_stopped(worker_pid)
        assert not (tmp_path / "launch.gate").exists()
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
            wrapper.wait(timeout=5)


def test_returns_stdout_stderr_and_returncode(tmp_path):
    result = run_contained_process(
        _request(
            tmp_path,
            "import sys; print('normal stdout'); print('normal stderr', file=sys.stderr)",
        )
    )

    assert result == ContainedProcessResult(0, "normal stdout\n", "normal stderr\n")


def test_returns_nonzero_result_without_losing_output(tmp_path):
    result = run_contained_process(
        _request(
            tmp_path,
            "import sys; print('failed stdout'); print('failed stderr', file=sys.stderr); raise SystemExit(7)",
        )
    )

    assert result == ContainedProcessResult(7, "failed stdout\n", "failed stderr\n")


@pytest.mark.parametrize("returncode", _HIGH_BIT_EXIT_CODES)
def test_preserves_high_bit_windows_exit_code(tmp_path, returncode):
    command = _exit_process_command(returncode)
    direct = subprocess.run(
        command,
        cwd=tmp_path,
        env=agent_subprocess_env(allowlist=True),
        check=False,
    )

    result = run_contained_process(
        ContainedProcessRequest(
            command=command,
            cwd=tmp_path,
            env=agent_subprocess_env(allowlist=True),
            timeout_seconds=10,
        )
    )

    assert direct.returncode == returncode
    assert result.returncode == direct.returncode


@pytest.mark.parametrize("returncode", _HIGH_BIT_EXIT_CODES)
def test_high_bit_windows_exit_code_is_preserved_in_called_process_error(tmp_path, returncode):
    command = _exit_process_command(returncode)
    direct = subprocess.run(
        command,
        cwd=tmp_path,
        env=agent_subprocess_env(allowlist=True),
        check=False,
    )
    result = run_contained_process(
        ContainedProcessRequest(
            command=command,
            cwd=tmp_path,
            env=agent_subprocess_env(allowlist=True),
            timeout_seconds=10,
        )
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        subprocess.CompletedProcess(command, result.returncode, result.stdout, result.stderr).check_returncode()

    assert direct.returncode == returncode
    assert exc_info.value.returncode == direct.returncode


def test_successful_command_exit_kills_child_and_grandchild(tmp_path):
    result, child_pid, grandchild_pid = _run_command_leaving_sleeping_descendants(tmp_path, 0)

    assert result.returncode == 0
    assert _wait_until_stopped(child_pid)
    assert _wait_until_stopped(grandchild_pid)


def test_nonzero_command_exit_kills_child_and_grandchild(tmp_path):
    result, child_pid, grandchild_pid = _run_command_leaving_sleeping_descendants(tmp_path, 7)

    assert result.returncode == 7
    assert _wait_until_stopped(child_pid)
    assert _wait_until_stopped(grandchild_pid)


def test_timeout_raises_with_captured_output(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        run_contained_process(
            _request(
                tmp_path,
                "import sys, time; print('partial stdout', flush=True); print('partial stderr', file=sys.stderr, flush=True); time.sleep(60)",
                timeout_seconds=1,
            )
        )

    assert exc_info.value.stdout == "partial stdout\n"
    assert exc_info.value.stderr == "partial stderr\n"


def test_timeout_kills_child_and_grandchild(tmp_path):
    child_pid_path = tmp_path / "child.pid"
    grandchild_pid_path = tmp_path / "grandchild.pid"
    grandchild_code = "import os, sys, time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); time.sleep(60)"
    child_code = (
        "import os, subprocess, sys, time; "
        "from pathlib import Path; "
        "Path(sys.argv[1]).write_text(str(os.getpid()), encoding='utf-8'); "
        "subprocess.Popen([sys.executable, '-c', sys.argv[3], sys.argv[2]]); "
        "time.sleep(60)"
    )
    request = ContainedProcessRequest(
        command=(sys.executable, "-c", child_code, str(child_pid_path), str(grandchild_pid_path), grandchild_code),
        cwd=tmp_path,
        env=agent_subprocess_env(allowlist=True),
        timeout_seconds=2,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        run_contained_process(request)

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    grandchild_pid = int(grandchild_pid_path.read_text(encoding="utf-8"))
    assert _wait_until_stopped(child_pid)
    assert _wait_until_stopped(grandchild_pid)


def test_worker_does_not_launch_command_before_gate(tmp_path):
    marker_path = tmp_path / "launched.txt"
    request_path = tmp_path / "request.json"
    gate_path = tmp_path / "launch.gate"
    request_path.write_text(
        json.dumps(
            {
                "command": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker_path)!r}).touch()"],
                "cwd": str(tmp_path),
                "env": agent_subprocess_env(allowlist=True),
            }
        ),
        encoding="utf-8",
    )
    worker = subprocess.Popen(
        [
            sys.executable,
            str(_WORKER_PATH),
            str(request_path),
            str(gate_path),
            "5",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        time.sleep(0.3)
        assert not marker_path.exists()

        gate_path.touch()
        stdout, stderr = worker.communicate(timeout=5)

        assert worker.returncode == 0, (stdout, stderr)
        assert marker_path.exists()
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait()


def test_uses_exact_supplied_environment_without_evaluator_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("EVALUATOR_SECRET", "must-not-leak")
    env = agent_subprocess_env({"VISIBLE_VALUE": "present"}, allowlist=True)
    result = run_contained_process(
        _request(
            tmp_path,
            "import json, os; print(json.dumps({'visible': os.environ.get('VISIBLE_VALUE'), 'secret': os.environ.get('EVALUATOR_SECRET')}))",
            env=env,
        )
    )

    assert json.loads(result.stdout) == {"visible": "present", "secret": None}


def test_serializes_optional_restricted_identity_and_cleans_temp_files(tmp_path, monkeypatch):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()
    captured_spec: dict[str, object] = {}
    captured_paths: list[Path] = []
    captured_command: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        request_path = Path(command[command.index("-RequestPath") + 1])
        worker_request_path = Path(command[command.index("-WorkerRequestPath") + 1])
        gate_path = Path(command[command.index("-GatePath") + 1])
        stdout_path = Path(command[command.index("-StdoutPath") + 1])
        stderr_path = Path(command[command.index("-StderrPath") + 1])
        captured_paths.extend((request_path, worker_request_path, gate_path, stdout_path, stderr_path))
        captured_spec.update(json.loads(request_path.read_text(encoding="utf-8")))
        assert request_path.exists()
        return subprocess.CompletedProcess(command, 0, stdout='{"returncode":0,"stdout":"","stderr":"","timed_out":false}\n', stderr="")

    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    monkeypatch.setattr("bcbench.agent.shared.contained_process.subprocess.run", fake_run)

    result = run_contained_process(
        ContainedProcessRequest(
            command=("agent", "--run"),
            cwd=tmp_path,
            env={"FLAG": "on"},
            timeout_seconds=30,
            identity=WindowsIdentity("restricted-user", "restricted-password", "RESTRICTED"),
        )
    )

    assert result == ContainedProcessResult(0, "", "")
    assert captured_spec["identity"] == {
        "username": "restricted-user",
        "password": "restricted-password",
        "domain": "RESTRICTED",
    }
    worker_path = Path(captured_command[captured_command.index("-WorkerPath") + 1])
    assert worker_path == _WORKER_PATH
    assert "-m" not in captured_command
    assert all(not path.exists() for path in captured_paths)


def test_missing_wrapper_script_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )

    with pytest.raises(FileNotFoundError, match=r"Invoke-ContainedProcess\.ps1"):
        run_contained_process(_request(tmp_path, "print('never launched')"))


def test_wrapper_launch_failure_raises_infrastructure_error(tmp_path, monkeypatch):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()
    failure = subprocess.CalledProcessError(1, ["pwsh"], output="", stderr="assignment failed")
    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    with (
        patch("bcbench.agent.shared.contained_process.subprocess.run", side_effect=failure),
        pytest.raises(ContainedProcessInfrastructureError) as exc_info,
    ):
        run_contained_process(_request(tmp_path, "print('never launched')"))

    assert exc_info.value.__cause__ is failure
    assert exc_info.value.wrapper_returncode == 1
    assert exc_info.value.wrapper_stdout == ""
    assert exc_info.value.wrapper_stderr == "assignment failed"


def test_wrapper_failure_includes_child_captures_and_wrapper_diagnostics(tmp_path, monkeypatch):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()
    wrapper_command: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        wrapper_command.extend(command)
        stdout_path = Path(command[command.index("-StdoutPath") + 1])
        stderr_path = Path(command[command.index("-StderrPath") + 1])
        stdout_path.write_bytes(b"child stdout\r\n")
        stderr_path.write_bytes(b"child stderr\r\n")
        raise subprocess.CalledProcessError(
            23,
            command,
            output="wrapper stdout diagnostic\r\n",
            stderr="wrapper stderr diagnostic\r\n",
        )

    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    monkeypatch.setattr("bcbench.agent.shared.contained_process.subprocess.run", fake_run)

    with pytest.raises(ContainedProcessInfrastructureError) as exc_info:
        run_contained_process(_request(tmp_path, "print('launched')"))

    assert isinstance(exc_info.value.__cause__, subprocess.CalledProcessError)
    assert exc_info.value.wrapper_returncode == 23
    assert exc_info.value.child_stdout == "child stdout\n"
    assert exc_info.value.child_stderr == "child stderr\n"
    assert exc_info.value.wrapper_stdout == "wrapper stdout diagnostic\n"
    assert exc_info.value.wrapper_stderr == "wrapper stderr diagnostic\n"


def test_wrapper_watchdog_timeout_raises_infrastructure_error_with_all_captures(tmp_path, monkeypatch):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()
    watchdog_timeout = 71

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout_path = Path(command[command.index("-StdoutPath") + 1])
        stderr_path = Path(command[command.index("-StderrPath") + 1])
        stdout_path.write_bytes(b"child stdout\r\n")
        stderr_path.write_bytes(b"child stderr\r\n")
        raise subprocess.TimeoutExpired(
            command,
            watchdog_timeout,
            output="wrapper stdout\r\n",
            stderr=b"wrapper stderr\r\n",
        )

    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    monkeypatch.setattr("bcbench.agent.shared.contained_process.subprocess.run", fake_run)

    with pytest.raises(ContainedProcessInfrastructureError) as exc_info:
        run_contained_process(_request(tmp_path, "print('launched')", timeout_seconds=31))

    assert exc_info.value.watchdog_timeout_seconds == watchdog_timeout
    assert exc_info.value.child_stdout == "child stdout\n"
    assert exc_info.value.child_stderr == "child stderr\n"
    assert exc_info.value.wrapper_stdout == "wrapper stdout\n"
    assert exc_info.value.output == "wrapper stdout\n"
    assert exc_info.value.wrapper_stderr == "wrapper stderr\n"
    assert exc_info.value.stderr == "wrapper stderr\n"


def test_wrapper_reported_timeout_remains_command_timeout(tmp_path, monkeypatch):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()
    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.subprocess.run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            stdout='{"returncode":null,"stdout":"command stdout","stderr":"command stderr","timed_out":true}\n',
            stderr="",
        ),
    )

    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        run_contained_process(_request(tmp_path, "print('launched')", timeout_seconds=13))

    assert exc_info.value.timeout == 13
    assert exc_info.value.stdout == "command stdout"
    assert exc_info.value.stderr == "command stderr"


@pytest.mark.parametrize(
    ("wrapper_stdout", "expected_cause"),
    [
        pytest.param("not JSON", json.JSONDecodeError, id="malformed-json"),
        pytest.param(
            '{"returncode":0,"stdout":"command stdout","stderr":"command stderr"}',
            ValueError,
            id="missing-field",
        ),
        pytest.param(
            '{"returncode":0,"stdout":"command stdout","stderr":"command stderr","timed_out":"false"}',
            TypeError,
            id="timed-out-wrong-type",
        ),
        pytest.param(
            '{"returncode":0,"stdout":1,"stderr":"command stderr","timed_out":false}',
            TypeError,
            id="stdout-wrong-type",
        ),
        pytest.param(
            '{"returncode":0,"stdout":"command stdout","stderr":null,"timed_out":false}',
            TypeError,
            id="stderr-wrong-type",
        ),
        pytest.param(
            '{"returncode":0,"stdout":"command stdout","stderr":"command stderr","timed_out":true}',
            ValueError,
            id="timeout-with-returncode",
        ),
        pytest.param(
            '{"returncode":null,"stdout":"command stdout","stderr":"command stderr","timed_out":false}',
            ValueError,
            id="false-success-null-returncode",
        ),
        pytest.param(
            '{"returncode":true,"stdout":"command stdout","stderr":"command stderr","timed_out":false}',
            TypeError,
            id="bool-returncode",
        ),
        pytest.param(
            '{"returncode":1.0,"stdout":"command stdout","stderr":"command stderr","timed_out":false}',
            TypeError,
            id="returncode-wrong-type",
        ),
        pytest.param(
            '{"returncode":-1,"stdout":"command stdout","stderr":"command stderr","timed_out":false}',
            ValueError,
            id="negative-returncode",
        ),
        pytest.param(
            '{"returncode":4294967296,"stdout":"command stdout","stderr":"command stderr","timed_out":false}',
            ValueError,
            id="out-of-range-returncode",
        ),
        pytest.param(
            '{"returncode":0,"stdout":"command stdout","stderr":"command stderr","timed_out":false,"unexpected":true}',
            ValueError,
            id="extra-field",
        ),
    ],
)
def test_invalid_wrapper_response_raises_infrastructure_error_with_all_diagnostics(
    tmp_path,
    monkeypatch,
    wrapper_stdout,
    expected_cause,
):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout_path = Path(command[command.index("-StdoutPath") + 1])
        stderr_path = Path(command[command.index("-StderrPath") + 1])
        stdout_path.write_bytes(b"child stdout\r\n")
        stderr_path.write_bytes(b"child stderr\r\n")
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=wrapper_stdout,
            stderr="wrapper stderr\r\n",
        )

    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    monkeypatch.setattr("bcbench.agent.shared.contained_process.subprocess.run", fake_run)

    with pytest.raises(ContainedProcessInfrastructureError) as exc_info:
        run_contained_process(_request(tmp_path, "print('launched')"))

    assert isinstance(exc_info.value.__cause__, expected_cause)
    assert exc_info.value.wrapper_returncode == 0
    assert exc_info.value.child_stdout == "child stdout\n"
    assert exc_info.value.child_stderr == "child stderr\n"
    assert exc_info.value.wrapper_stdout == wrapper_stdout
    assert exc_info.value.wrapper_stderr == "wrapper stderr\n"


@pytest.mark.e2e
def test_windows_identity_isolated_environment_workspace_and_docker_access(tmp_path, monkeypatch):
    if not _is_elevated():
        pytest.skip("requires an elevated Windows process to create and remove a disposable local user")
    if shutil.which("docker") is None:
        pytest.skip("requires the Docker CLI for the WindowsIdentity isolation e2e test")
    evaluator_docker = subprocess.run(["docker", "version"], capture_output=True, text=True, timeout=15, check=False)
    if evaluator_docker.returncode != 0:
        pytest.skip("requires evaluator access to the Docker daemon for the WindowsIdentity isolation e2e test")
    if not _can_open_named_pipe(r"\\.\pipe\docker_engine"):
        pytest.skip(r"requires evaluator access to \\.\pipe\docker_engine for the WindowsIdentity isolation e2e test")

    username = f"bcbench-e2e-{secrets.token_hex(3)}"
    password = _random_password()
    workspace = tmp_path / "restricted-workspace"
    evaluator_only = tmp_path / "evaluator-only"
    workspace.mkdir()
    evaluator_only.mkdir()
    runtime_directory = workspace / "python-runtime"
    shutil.copytree(Path(sys.base_prefix), runtime_directory)
    runtime_python = runtime_directory / "python.exe"
    monkeypatch.setattr(contained_process_module.sys, "executable", str(runtime_python))
    secret_path = evaluator_only / "secret.txt"
    secret_path.write_text("evaluator-secret", encoding="utf-8")
    try:
        _run_powershell(
            """
$password = ConvertTo-SecureString $env:BCBENCH_E2E_PASSWORD -AsPlainText -Force
New-LocalUser -Name $env:BCBENCH_E2E_USER -Password $password -AccountNeverExpires -PasswordNeverExpires | Out-Null
Add-LocalGroupMember -SID ([Security.Principal.SecurityIdentifier]"S-1-5-32-545") -Member $env:BCBENCH_E2E_USER
""",
            {
                "BCBENCH_E2E_USER": username,
                "BCBENCH_E2E_PASSWORD": password,
            },
        )
        _run_powershell(
            """
$account = [Security.Principal.NTAccount]::new([Environment]::MachineName, $env:BCBENCH_E2E_USER)
$root = [IO.DirectoryInfo]::new($env:BCBENCH_E2E_ROOT)
$rootAcl = [IO.FileSystemAclExtensions]::GetAccessControl($root)
$rootAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $account,
    [Security.AccessControl.FileSystemRights]::ReadAndExecute,
    [Security.AccessControl.InheritanceFlags]::None,
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)) | Out-Null
[IO.FileSystemAclExtensions]::SetAccessControl($root, $rootAcl)

$workspace = [IO.DirectoryInfo]::new($env:BCBENCH_E2E_WORKSPACE)
$workspaceAcl = [IO.FileSystemAclExtensions]::GetAccessControl($workspace)
$workspaceAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    $account,
    [Security.AccessControl.FileSystemRights]::Modify,
    [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit",
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AccessControlType]::Allow
)) | Out-Null
[IO.FileSystemAclExtensions]::SetAccessControl($workspace, $workspaceAcl)

$evaluator = [Security.Principal.WindowsIdentity]::GetCurrent().User
$system = [Security.Principal.SecurityIdentifier]::new("S-1-5-18")
$privateDirectory = [IO.DirectoryInfo]::new($env:BCBENCH_E2E_PRIVATE)
$privateAcl = [Security.AccessControl.DirectorySecurity]::new()
$privateAcl.SetAccessRuleProtection($true, $false)
foreach ($sid in @($evaluator, $system)) {
    $privateAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        $sid,
        [Security.AccessControl.FileSystemRights]::FullControl,
        [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit",
        [Security.AccessControl.PropagationFlags]::None,
        [Security.AccessControl.AccessControlType]::Allow
    )) | Out-Null
}
[IO.FileSystemAclExtensions]::SetAccessControl($privateDirectory, $privateAcl)
""",
            {
                "BCBENCH_E2E_USER": username,
                "BCBENCH_E2E_ROOT": str(tmp_path),
                "BCBENCH_E2E_WORKSPACE": str(workspace),
                "BCBENCH_E2E_PRIVATE": str(evaluator_only),
            },
        )

        child_code = r"""
import ctypes
import json
import os
import subprocess
from pathlib import Path

workspace = Path.cwd()
(workspace / "restricted-write.txt").write_text("written", encoding="utf-8")
try:
    Path(os.environ["BCBENCH_E2E_SECRET_PATH"]).read_text(encoding="utf-8")
except PermissionError:
    secret_denied = True
else:
    secret_denied = False

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = (
    ctypes.c_wchar_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
)
kernel32.CreateFileW.restype = ctypes.c_void_p
pipe_handle = kernel32.CreateFileW(r"\\.\pipe\docker_engine", 0xC0000000, 0, None, 3, 0, None)
invalid_handle = ctypes.c_void_p(-1).value
if pipe_handle == invalid_handle:
    pipe_denied = ctypes.get_last_error() == 5
else:
    pipe_denied = False
    kernel32.CloseHandle(pipe_handle)

docker = subprocess.run(["docker", "version"], capture_output=True, text=True, timeout=15, check=False)
print(json.dumps({
    "environment": dict(os.environ),
    "secret_denied": secret_denied,
    "pipe_denied": pipe_denied,
    "docker_denied": docker.returncode != 0,
}))
"""
        env = {
            "PATH": os.environ["PATH"],
            "PATHEXT": os.environ["PATHEXT"],
            "SYSTEMROOT": os.environ["SYSTEMROOT"],
            "COMSPEC": os.environ["COMSPEC"],
            "TEMP": str(workspace),
            "TMP": str(workspace),
            "BCBENCH_E2E_TOKEN": "exact-value",
            "BCBENCH_E2E_SECRET_PATH": str(secret_path),
        }
        result = run_contained_process(
            ContainedProcessRequest(
                command=(str(runtime_python), "-c", child_code),
                cwd=workspace,
                env=env,
                timeout_seconds=30,
                identity=WindowsIdentity(username, password),
            )
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert {key.upper(): value for key, value in payload["environment"].items()} == env
        assert (workspace / "restricted-write.txt").read_text(encoding="utf-8") == "written"
        assert payload["secret_denied"] is True
        assert payload["pipe_denied"] is True
        assert payload["docker_denied"] is True
    finally:
        try:
            _run_powershell(
                "Remove-LocalUser -Name $env:BCBENCH_E2E_USER -ErrorAction SilentlyContinue",
                {"BCBENCH_E2E_USER": username},
            )
        finally:
            if workspace.exists():
                shutil.rmtree(workspace)
            if evaluator_only.exists():
                shutil.rmtree(evaluator_only)
