import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Self

if os.name == "nt":
    from bcbench.diagnostics.windows_job import CREATE_SUSPENDED, WindowsJob


class DiagnosticReadError(Exception):
    pass


class DiagnosticProcess:
    def __init__(self, command: Sequence[str], cwd: Path, env: Mapping[str, str] | None) -> None:
        self._job = WindowsJob() if os.name == "nt" else None
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=os.name != "nt",
                creationflags=CREATE_SUSPENDED if os.name == "nt" else 0,
            )
            if self._job is not None:
                self._job.assign_and_resume(process.pid)
        except OSError:
            if self._job is not None:
                self._job.close()
            if process is not None:
                process.kill()
                process.wait(timeout=5)
                if process.stdout is not None:
                    process.stdout.close()
            raise
        self.process = process
        self._tree_stopped = False
        self.cleanup_complete = False
        self._lines: queue.Queue[tuple[str, str]] = queue.Queue()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            with self.process.stdout:
                for line in self.process.stdout:
                    self._lines.put(("line", line))
        except (OSError, ValueError):
            self._lines.put(("error", ""))
        finally:
            self._lines.put(("eof", ""))

    def lines(self, deadline: float) -> Iterator[str]:
        drain_deadline: float | None = None
        while True:
            if drain_deadline is None and self.process.poll() is not None:
                self._terminate_tree()
                # Stopping descendants closes inherited handles; buffered parent output remains readable.
                drain_deadline = time.monotonic() + 1
            remaining = (deadline if drain_deadline is None else drain_deadline) - time.monotonic()
            if remaining <= 0:
                if drain_deadline is not None:
                    raise DiagnosticReadError("Stdout did not close after process-tree cleanup")
                raise subprocess.TimeoutExpired("diagnostic subprocess", 0)
            try:
                kind, line = self._lines.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if kind == "eof":
                return
            if kind == "error":
                raise DiagnosticReadError
            yield line
            if drain_deadline is not None:
                drain_deadline = time.monotonic() + 1

    def wait(self, deadline: float) -> int:
        return self.process.wait(timeout=max(0, deadline - time.monotonic()))

    def _terminate_tree(self) -> None:
        if self._tree_stopped:
            return
        if self._job is not None:
            self._job.terminate()
        else:
            with suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGKILL)
        self._tree_stopped = True

    def close(self) -> None:
        try:
            self._terminate_tree()
            self.process.wait(timeout=5)
            self._reader.join(timeout=1)
            self.cleanup_complete = self._tree_stopped and not self._reader.is_alive()
        except (OSError, subprocess.TimeoutExpired):
            self.cleanup_complete = False
        finally:
            if self._job is not None:
                try:
                    self._job.close()
                except OSError:
                    self.cleanup_complete = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
