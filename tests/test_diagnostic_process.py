import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.shared.diagnostic_process import DiagnosticProcess

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process-tree ownership")


class ChildProcessHandle:
    def __init__(self, pid: int):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.OpenProcess(0x100001, False, pid)  # SYNCHRONIZE | PROCESS_TERMINATE
        assert self.handle, ctypes.WinError(ctypes.get_last_error())

    def wait(self, milliseconds: int) -> bool:
        return self.kernel.WaitForSingleObject(self.handle, milliseconds) == 0

    def close(self):
        if not self.wait(0):
            self.kernel.TerminateProcess(self.handle, 1)
            self.wait(5000)
        self.kernel.CloseHandle(self.handle)


@pytest.mark.parametrize("inherit_stdout", [True, False])
def test_exited_parent_does_not_leave_descendant_or_block_stdout(tmp_path: Path, inherit_stdout: bool):
    release = tmp_path / "exit-parent"
    script = f"""
import pathlib, subprocess, sys, time
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(20)"],
    stdout={"sys.stdout" if inherit_stdout else "subprocess.DEVNULL"},
    stderr=subprocess.DEVNULL,
)
print(child.pid, flush=True)
while not pathlib.Path({str(release)!r}).exists():
    time.sleep(0.01)
"""
    child = None
    try:
        with DiagnosticProcess([sys.executable, "-u", "-c", script], tmp_path, {}) as process:
            lines = process.lines(time.monotonic() + 5)
            child = ChildProcessHandle(int(next(lines)))
            assert not child.wait(0)
            release.write_text("exit", encoding="utf-8")
            assert process.wait(time.monotonic() + 5) == 0
            assert list(lines) == []
        assert process.cleanup_complete
        assert child.wait(1000), "Descendant survived successful process cleanup"
    finally:
        if child is not None:
            child.close()


def test_timeout_terminates_running_parent_and_descendant(tmp_path: Path):
    script = """
import subprocess, sys, time
child = subprocess.Popen(
    [sys.executable, "-c", "import time; time.sleep(20)"],
    stdout=sys.stdout, stderr=subprocess.DEVNULL,
)
print(child.pid, flush=True)
time.sleep(20)
"""
    child = None
    try:
        with DiagnosticProcess([sys.executable, "-u", "-c", script], tmp_path, {}) as process:
            lines = process.lines(time.monotonic() + 5)
            child = ChildProcessHandle(int(next(lines)))
            with pytest.raises(subprocess.TimeoutExpired):
                list(process.lines(time.monotonic()))
        assert process.cleanup_complete
        assert child.wait(1000)
    finally:
        if child is not None:
            child.close()


def test_completed_process_output_survives_slow_diagnostic_consumer(tmp_path: Path):
    with DiagnosticProcess([sys.executable, "-u", "-c", "print('first'); print('last')"], tmp_path, {}) as process:
        assert process.wait(time.monotonic() + 5) == 0
        lines = process.lines(time.monotonic() + 5)
        assert next(lines) == "first\n"
        time.sleep(1.1)
        assert list(lines) == ["last\n"]
    assert process.cleanup_complete


def test_resume_failure_reaps_suspended_process_and_closes_pipes(tmp_path: Path):
    processes = []
    popen = subprocess.Popen

    def track_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    with (
        patch("bcbench.agent.shared.diagnostic_process.subprocess.Popen", side_effect=track_process),
        patch("bcbench.diagnostics.windows_job._resume_initial_thread", side_effect=OSError("Cannot resume")),
        pytest.raises(OSError, match="Cannot resume"),
    ):
        DiagnosticProcess([sys.executable, "-c", "raise SystemExit(99)"], tmp_path, {})
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert processes[0].returncode != 99
    assert processes[0].stdin is None
    assert processes[0].stdout.closed


def test_cleanup_does_not_terminate_unrelated_process(tmp_path: Path):
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with DiagnosticProcess([sys.executable, "-c", "pass"], tmp_path, {}) as process:
            assert process.wait(time.monotonic() + 5) == 0
        assert process.cleanup_complete
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait(timeout=5)
