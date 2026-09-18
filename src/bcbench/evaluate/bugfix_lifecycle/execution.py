import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from bcbench.evaluate.bugfix_lifecycle.models import ProvisionedLifecycleResources
from bcbench.evaluate.bugfix_lifecycle.path_safety import reject_reparse_components
from bcbench.exceptions import CleanupInfrastructureError


@dataclass(frozen=True)
class WorkflowExecution:
    resources: ProvisionedLifecycleResources

    @property
    def path(self) -> Path:
        return self.resources.paths.protected_root / "workflow-execution.json"

    @property
    def enabled(self) -> bool:
        return self.path.exists() or (self.path.parent / "workflow-setup.json").exists()

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock = self.path.with_suffix(".lock")
        reject_reparse_components(lock, self.path.parent)
        try:
            stream = lock.open("x", encoding="utf-8")
        except FileExistsError as error:
            raise CleanupInfrastructureError("Workflow execution handoff is locked or interrupted") from error
        try:
            with stream:
                yield
        finally:
            lock.unlink()

    def _read(self) -> dict[str, object]:
        reject_reparse_components(self.path, self.path.parent)
        payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("container_id") != self.resources.expected_container_id or payload.get("invocation_id") != self.resources.expected_container_invocation_id:
            raise CleanupInfrastructureError("Workflow execution ownership does not match setup")
        return payload

    def _transition(self, allowed: set[str], status: str) -> None:
        if not self.enabled:
            return
        with self._lock():
            payload = self._read()
            if payload.get("status") not in allowed:
                raise CleanupInfrastructureError(f"Cannot enter {status} from workflow execution state {payload.get('status')}")
            payload["status"] = status
            self._write(payload)

    def _write(self, payload: dict[str, object]) -> None:
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)

    def begin_cli(self) -> None:
        self._transition({"not_started", "launching"}, "cli_running")

    def begin_lifecycle(self) -> None:
        self._transition({"not_started", "cli_running"}, "running")

    def begin_rehearsal(self) -> None:
        self._transition({"launching", "cli_running", "running"}, "rehearsal_running")

    def finish_rehearsal(self, *, resume_lifecycle: bool) -> None:
        self._transition({"rehearsal_running"}, "running" if resume_lifecycle else "shutdown_verified")

    def verify_shutdown(self, verification: Callable[[], None]) -> None:
        if not self.enabled:
            verification()
            return
        with self._lock():
            payload = self._read()
            if payload.get("status") != "running":
                raise CleanupInfrastructureError("Workflow execution cannot verify shutdown while a rehearsal or another owner is active")
            try:
                verification()
            except BaseException as error:
                raise CleanupInfrastructureError("Workflow execution shutdown could not be verified") from error
            payload["status"] = "shutdown_verified"
            self._write(payload)

    def require_shutdown(self) -> None:
        if not self.enabled:
            return
        with self._lock():
            if self._read().get("status") != "shutdown_verified":
                raise CleanupInfrastructureError("Workflow execution shutdown is not verified; retain resources")
