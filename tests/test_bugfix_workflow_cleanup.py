import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_lifecycle import workflow_cleanup
from bcbench.exceptions import CleanupInfrastructureError

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object cleanup")


@pytest.mark.parametrize("hang", [False, True])
def test_cleanup_deadline_contains_hanging_operation_and_preserves_quarantine(tmp_path: Path, hang: bool) -> None:
    entry = tmp_path / "entry"
    protected = tmp_path / "protected"
    entry.mkdir()
    protected.mkdir()
    (entry / "agent-workspace").mkdir()
    state = {
        "Status": "ready",
        "InstanceId": "test",
        "ContainerName": "bc-test",
        "ContainerId": "owned-id",
        "ContainerInvocationId": "owned-label",
        "EntryRoot": str(entry),
        "ProtectedRoot": str(protected),
        "AgentIdentity": {"Username": "bcb-1234567-abcdef", "Sid": "S-1-5-21-1-2-3-1001"},
        "AgentBcIdentity": None,
        "AclTransaction": None,
        "OwnedCompilerHelperRoots": [],
        "SetupCleanupErrors": [],
    }
    (protected / "workflow-setup.json").write_text(json.dumps(state))
    (protected / "workflow-execution.json").write_text(
        json.dumps(
            {
                "status": "not_started",
                "container_id": "owned-id",
                "invocation_id": "owned-label",
            }
        )
    )
    worker = tmp_path / "worker.py"
    worker.write_text(
        r"""
import json
import subprocess
import sys
from pathlib import Path
entry = Path(sys.argv[sys.argv.index("-EntryRoot") + 1])
protected = Path(sys.argv[sys.argv.index("-ProtectedRoot") + 1])
if HANG:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (protected / "child.pid").write_text(str(child.pid))
    child.wait()
(entry / "agent-workspace").rmdir()
entry.rmdir()
(protected / "workflow-cleanup.json").write_text(json.dumps({"status": "success"}))
""".replace("HANG", str(hang))
    )
    start = time.monotonic()
    if hang:
        with pytest.raises(CleanupInfrastructureError) as failure:
            workflow_cleanup.complete_workflow_cleanup(entry, protected, "bc-test", timeout_seconds=3, worker_command=(sys.executable, str(worker)))
        assert str(failure.value) in {"Cleanup exceeded its total deadline", "Cleanup containment shutdown is unverified"}
        assert time.monotonic() - start < 48
        assert entry.exists()
        assert (protected / "quarantine.json").exists()
        pending = protected.with_name(protected.name + ".cleanup-pending.quarantine.json")
        assert pending.exists()
        attempt = json.loads(pending.read_text())
        assert attempt["status"] == "failed"
        assert attempt["worker_shutdown"] in {"verified", "unverified"}
        if attempt["worker_shutdown"] == "unverified":
            assert str(failure.value) == "Cleanup containment shutdown is unverified"
        pid = int((protected / "child.pid").read_text(encoding="utf-8-sig"))
        probe = subprocess.run(["pwsh", "-NoProfile", "-Command", f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ exit 1 }}"], check=False)
        assert probe.returncode == 0
    else:
        workflow_cleanup.complete_workflow_cleanup(entry, protected, "bc-test", timeout_seconds=15, worker_command=(sys.executable, str(worker)))
        assert not entry.exists()
        assert not protected.with_name(protected.name + ".cleanup-pending.quarantine.json").exists()
        assert not (protected / "quarantine.json").exists()
        assert json.loads((protected / "workflow-cleanup.json").read_text())["status"] == "success"


def test_cleanup_never_retries_an_interrupted_worker_attempt(tmp_path: Path) -> None:
    protected = tmp_path / "protected"
    pending = protected.with_name(protected.name + ".cleanup-pending.quarantine.json")
    pending.write_text('{"status":"running","worker_shutdown":"unverified"}')
    with pytest.raises(CleanupInfrastructureError, match="interrupted"):
        workflow_cleanup.complete_workflow_cleanup(tmp_path / "entry", protected, "bc-test", timeout_seconds=1)
    assert json.loads(pending.read_text())["worker_shutdown"] == "unverified"
    assert (protected / "quarantine.json").exists()


def test_packaged_powershell_is_rejected_before_cleanup_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    protected = tmp_path / "protected"
    monkeypatch.setattr(workflow_cleanup.shutil, "which", lambda _: r"C:\Program Files\WindowsApps\PowerShell\pwsh.exe")
    with pytest.raises(CleanupInfrastructureError, match="non-packaged"):
        workflow_cleanup.complete_workflow_cleanup(tmp_path / "entry", protected, "bc-test")
    assert (protected / "quarantine.json").exists()


def test_supervisor_interrupt_preserves_unverified_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    protected = tmp_path / "protected"

    def interrupt(_request):
        raise KeyboardInterrupt("workflow cancelled")

    monkeypatch.setattr(workflow_cleanup, "run_contained_process", interrupt)
    with pytest.raises(CleanupInfrastructureError, match="interrupted"):
        workflow_cleanup.complete_workflow_cleanup(tmp_path / "entry", protected, "bc-test", worker_command=(sys.executable, "-c", "pass"))
    pending = protected.with_name(protected.name + ".cleanup-pending.quarantine.json")
    assert json.loads(pending.read_text())["worker_shutdown"] == "unverified"
    assert json.loads((protected / "workflow-cleanup.json").read_text())["status"] == "failed"
