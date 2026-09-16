import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bcbench.agent.shared.contained_process import (
    AgentExecutionPolicy,
    ContainedProcessRequest,
    ContainedProcessResult,
    WindowsIdentity,
    run_contained_process,
)
from bcbench.agent.shared.env import agent_subprocess_env

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects are required")

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


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
    script_path = Path(__file__).parents[1] / "scripts" / "Invoke-ContainedProcess.ps1"
    source = script_path.read_text(encoding="utf-8")
    powershell_source = source.split("'@", maxsplit=1)[1]

    assert "public static IntPtr CreateKillOnCloseJob()" in source
    assert "public static void AssignProcess(IntPtr job, IntPtr process)" in source
    assert "public static void TerminateJob(IntPtr job, uint exitCode)" in source
    assert "public static void CloseHandle(IntPtr handle)" in source
    assert "private static extern IntPtr CreateJobObject(" in source
    assert "private static extern bool SetInformationJobObject(" in source
    assert "private static extern bool AssignProcessToJobObject(" in source
    assert "private static extern bool TerminateJobObject(" in source
    assert "private static extern bool CloseHandleNative(" in source
    for operation in (
        "CreateJobObject",
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "TerminateJobObject",
        "CloseHandle",
    ):
        assert f'"{operation} failed"' in source
    assert "$job = [BCBenchJobObject]::CreateKillOnCloseJob()" in powershell_source
    assert "[BCBenchJobObject]::AssignProcess($job, $process.Handle)" in powershell_source
    assert "[BCBenchJobObject]::TerminateJob($job, 1)" in powershell_source
    assert "[BCBenchJobObject]::CloseHandle($job)" in powershell_source
    assert "[BCBenchJobObject]::CreateJobObject(" not in powershell_source
    assert "[BCBenchJobObject]::SetInformationJobObject(" not in powershell_source
    assert "[BCBenchJobObject]::AssignProcessToJobObject(" not in powershell_source
    assert "[BCBenchJobObject]::TerminateJobObject(" not in powershell_source


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
            "-m",
            "bcbench.agent.shared.contained_process_worker",
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

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
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
    assert all(not path.exists() for path in captured_paths)


def test_missing_wrapper_script_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )

    with pytest.raises(FileNotFoundError, match=r"Invoke-ContainedProcess\.ps1"):
        run_contained_process(_request(tmp_path, "print('never launched')"))


def test_wrapper_launch_failure_raises_called_process_error(tmp_path, monkeypatch):
    script_path = tmp_path / "Invoke-ContainedProcess.ps1"
    script_path.touch()
    failure = subprocess.CalledProcessError(1, ["pwsh"], output="", stderr="assignment failed")
    monkeypatch.setattr(
        "bcbench.agent.shared.contained_process.get_config",
        lambda: SimpleNamespace(paths=SimpleNamespace(ps_script_path=tmp_path)),
    )
    with (
        patch("bcbench.agent.shared.contained_process.subprocess.run", side_effect=failure),
        pytest.raises(subprocess.CalledProcessError) as exc_info,
    ):
        run_contained_process(_request(tmp_path, "print('never launched')"))

    assert exc_info.value.stderr == "assignment failed"


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

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_contained_process(_request(tmp_path, "print('launched')"))

    assert exc_info.value.returncode == 23
    assert exc_info.value.cmd == wrapper_command
    assert exc_info.value.stdout == "child stdout\nwrapper stdout diagnostic\n"
    assert exc_info.value.stderr == "child stderr\nwrapper stderr diagnostic\n"
