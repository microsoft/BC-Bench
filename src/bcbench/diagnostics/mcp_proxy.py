import logging
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from uuid import UUID, uuid4

from bcbench.diagnostics.mcp_diagnostics import SafeDiagnosticSnapshot
from bcbench.diagnostics.mcp_observation import McpObservation

if os.name == "nt":
    from bcbench.diagnostics.windows_job import CREATE_SUSPENDED, WindowsJob

type ObservationValue = bytes | str | dict[str, str | int | None]


class ObservationWorker:
    def __init__(self, snapshot: SafeDiagnosticSnapshot) -> None:
        self.observation = McpObservation(snapshot)
        self.queue: queue.Queue[tuple[str, ObservationValue]] = queue.Queue(maxsize=256)
        self.dropped = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, kind: str, value: ObservationValue) -> None:
        try:
            self.queue.put_nowait((kind, value))
        except queue.Full:
            self.dropped.set()

    def _run(self) -> None:
        last_save = time.monotonic()
        dirty = False
        while True:
            try:
                event = self.queue.get(timeout=0.1)
            except queue.Empty:
                if self.stopping.is_set():
                    break
                if dirty:
                    self.observation.save()
                    dirty = False
                continue
            if self.dropped.is_set():
                self.observation.issue("observer_queue_overflow")
            kind, value = event
            dirty = True
            if kind == "status" and isinstance(value, dict):
                self.observation.state["process"].update(value)
            elif kind == "eof" and isinstance(value, str):
                self.observation.eof(value)
            elif kind == "interrupted" and isinstance(value, str):
                self.observation.issue(f"{value}_relay_interrupted")
            elif isinstance(value, bytes) and not self.dropped.is_set():
                self.observation.feed(kind, value)
            if kind in ("status", "eof", "interrupted") or time.monotonic() - last_save >= 0.1:
                self.observation.save()
                last_save = time.monotonic()
                dirty = False
        if self.dropped.is_set():
            self.observation.issue("observer_queue_overflow")
        self.observation.save()

    def close(self) -> None:
        self.stopping.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            sys.stderr.write("BC-Bench MCP observer: snapshot writer did not finish\n")


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written == 0:
            raise BrokenPipeError
        view = view[written:]


def relay_server(command: Sequence[str], snapshot: SafeDiagnosticSnapshot, env: Mapping[str, str]) -> int:
    worker = ObservationWorker(snapshot)
    job = None
    process: subprocess.Popen[bytes] | None = None
    output_broken = threading.Event()
    threads: list[threading.Thread] = []
    stage = "job_create"
    termination = "natural_exit"
    cleanup = False

    def relay(source: int, target: int, direction: str) -> None:
        source_eof = False
        try:
            while True:
                data = os.read(source, 65536)
                if not data:
                    source_eof = True
                    break
                # Record requests before forwarding, so a fast response cannot overtake them.
                if direction != "stderr":
                    worker.submit(direction, data)
                try:
                    _write_all(target, data)
                except OSError as error:
                    worker.submit("status", {f"{direction}_write_error": error.errno})
                    if direction == "server":
                        output_broken.set()
                    if direction != "stderr":
                        break
                    continue
        except OSError as error:
            worker.submit("status", {f"{direction}_read_error": error.errno})
            if direction == "server":
                output_broken.set()
        finally:
            if source_eof and direction != "stderr":
                worker.submit("eof", direction)
            elif direction != "stderr":
                worker.submit("interrupted", direction)
            if direction == "client" and process is not None and process.stdin is not None:
                with suppress(OSError):
                    process.stdin.close()

    def terminate_tree() -> None:
        nonlocal cleanup
        if job is not None:
            job.terminate()
        elif os.name != "nt" and process is not None:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        cleanup = True

    try:
        if os.name == "nt":
            job = WindowsJob()
        stage = "process_spawn"
        worker.submit("status", {"stage": stage})
        process = subprocess.Popen(
            command,
            env=dict(env),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=os.name != "nt",
            creationflags=CREATE_SUSPENDED if os.name == "nt" else 0,
        )
        stage = "job_assign_resume"
        if job is not None:
            job.assign_and_resume(process.pid)
        worker.submit("status", {"stage": "child_running"})
        stage = "child_io"
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        for source, target, direction in (
            (sys.stdin.fileno(), process.stdin.fileno(), "client"),
            (process.stdout.fileno(), sys.stdout.fileno(), "server"),
            (process.stderr.fileno(), sys.stderr.fileno(), "stderr"),
        ):
            thread = threading.Thread(target=relay, args=(source, target, direction), daemon=True)
            threads.append(thread)
            thread.start()
        while process.poll() is None:
            if output_broken.is_set():
                termination = "downstream_closed"
                terminate_tree()
                break
            time.sleep(0.02)
        code = process.wait(timeout=5)
        worker.submit("status", {"stage": "child_exited", "exit_code": code, "termination": termination})
    except OSError as error:
        worker.submit("status", {"stage": "failed", "failure_stage": stage, "os_error": getattr(error, "winerror", None) or error.errno})
        return 1
    except subprocess.TimeoutExpired:
        worker.submit("status", {"stage": "failed", "failure_stage": "child_shutdown_timeout"})
        return 1
    except KeyboardInterrupt:
        worker.submit("status", {"stage": "interrupted"})
        return 130
    else:
        return code
    finally:
        try:
            if process is not None:
                terminate_tree()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            cleanup = False
        finally:
            if job is not None:
                try:
                    job.close()
                except OSError:
                    cleanup = False
        for thread in threads[1:]:
            thread.join(timeout=2)
        for stream in (process.stdout, process.stderr) if process is not None else ():
            if stream is not None and all(not thread.is_alive() for thread in threads[1:]):
                stream.close()
        worker.submit("status", {"cleanup": "complete" if cleanup and all(not thread.is_alive() for thread in threads[1:]) else "unavailable"})
        worker.close()


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 4 or args[2] != "--":
        sys.stderr.write("BC-Bench MCP observer: invalid launch arguments\n")
        return 2
    try:
        invocation_id = UUID(args[1]).hex
    except ValueError:
        sys.stderr.write("BC-Bench MCP observer: invalid invocation identifier\n")
        return 2
    if os.name == "nt":
        import msvcrt

        for stream in (sys.stdin, sys.stdout, sys.stderr):
            msvcrt.setmode(stream.fileno(), os.O_BINARY)
    logger = logging.getLogger("bcbench.diagnostics.mcp_diagnostics")
    logger.handlers = [logging.StreamHandler(sys.stderr)]
    logger.propagate = False
    snapshot = SafeDiagnosticSnapshot(Path(args[0]), invocation_id=invocation_id, connection_id=uuid4().hex)
    return relay_server(args[3:], snapshot, os.environ)


if __name__ == "__main__":
    raise SystemExit(main())
