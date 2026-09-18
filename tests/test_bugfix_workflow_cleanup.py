import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bcbench.agent.shared import contained_process
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


@pytest.mark.parametrize("failure", ["missing-runtime", "packaged-runtime", "pending", "startup-interruption"])
@pytest.mark.parametrize("ownership", ["owned", "foreign-container", "foreign-root", "invalid-account", "missing", "malformed"])
def test_startup_failure_records_inability_to_secure_identity_without_touching_foreign_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    ownership: str,
) -> None:
    entry = tmp_path / "entry"
    protected = tmp_path / "protected"
    entry.mkdir()
    protected.mkdir()
    retained = entry / "retain.txt"
    retained.write_text("owned resources")
    state = {
        "EntryRoot": str(entry),
        "ProtectedRoot": str(protected),
        "ContainerName": "bc-test",
        "ContainerId": "owned-container-id",
        "ContainerInvocationId": "owned-invocation-id",
        "AgentIdentity": {"Username": "bcb-1234567-abcdef", "Sid": "S-1-5-21-1-2-3-1001"},
    }
    if ownership == "foreign-container":
        state["ContainerName"] = "foreign-container"
    elif ownership == "foreign-root":
        state["EntryRoot"] = str(tmp_path / "foreign-entry")
    elif ownership == "invalid-account":
        state["AgentIdentity"] = {"Username": "administrator", "Sid": "S-1-5-21-1-2-3-500"}
    setup = protected / "workflow-setup.json"
    if ownership != "missing":
        setup.write_text("not-json" if ownership == "malformed" else json.dumps(state), encoding="utf-8")
    setup_reads = []
    open_path = Path.open

    def record_setup_read(path, *args, **kwargs):
        if path == setup:
            setup_reads.append(path)
        return open_path(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record_setup_read)
    launches = []

    def launch(request):
        launches.append(request)
        raise KeyboardInterrupt("cancelled before worker creation")

    monkeypatch.setattr(workflow_cleanup, "run_contained_process", launch)
    runtime = None if failure == "missing-runtime" else r"C:\Program Files\WindowsApps\PowerShell\pwsh.exe"
    monkeypatch.setattr(workflow_cleanup.shutil, "which", lambda _: runtime)
    pending = protected.with_name(protected.name + ".cleanup-pending.quarantine.json")
    if failure == "pending":
        pending.write_text('{"status":"running","worker_shutdown":"unverified"}')
    worker_command = (sys.executable, "-c", "pass") if failure == "startup-interruption" else None
    with pytest.raises(CleanupInfrastructureError):
        workflow_cleanup.complete_workflow_cleanup(entry, protected, "bc-test", worker_command=worker_command)
    assert setup_reads
    assert len(launches) == (1 if failure == "startup-interruption" else 0)
    assert retained.read_text() == "owned resources"
    evidence = json.loads((protected / "workflow-cleanup-worker.json").read_text())
    security = evidence["identity_security"]
    assert security["status"] == "unverified"
    assert security["local_identity_verified"] is False
    assert security["reason"]
    assert evidence["status"] == "failed"
    assert json.loads((protected / "quarantine.json").read_text())["identity_security"] == security
    if ownership == "owned":
        assert security["ownership"] == "setup_record_validated"
        assert security["username"] == "bcb-1234567-abcdef"
        assert security["sid"] == "S-1-5-21-1-2-3-1001"
    else:
        assert security["ownership"] == "unverified"
        assert "username" not in security
        assert "sid" not in security
    if failure == "pending":
        assert pending.read_text() == '{"status":"running","worker_shutdown":"unverified"}'


def test_cleanup_credentials_never_enter_actual_contained_request_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_names = (
        "BC_SERVER_PASSWORD",
        "BCBENCH_LIFECYCLE_AGENT_OS_PASSWORD",
        "BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD",
        "BCBENCH_LIFECYCLE_EVALUATOR_CONTAINER_CONFIG",
        "BCBENCH_LIFECYCLE_AGENT_CONTAINER_CONFIG",
        "COPILOT_GITHUB_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ADO_TOKEN",
        "AZURE_CLIENT_SECRET",
        "UNRELATED_API_KEY",
    )
    secrets = {name: f"cleanup-secret-sentinel-{index}" for index, name in enumerate(secret_names)}
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("BCBENCH_LIFECYCLE_ENTRY_ROOT", "setup-env-must-not-be-serialized")
    monkeypatch.setenv("CLEANUP_UNRECOGNIZED_ENV", "must-not-be-forwarded")
    serialized = {}
    write_request = contained_process._write_request
    parse_result = contained_process._parse_wrapper_result
    request_root = None

    def capture_request(path, request):
        nonlocal request_root
        write_request(path, request)
        request_root = path.parent.parent
        serialized["private"] = path.read_text(encoding="utf-8")

    def capture_worker_request(output):
        assert request_root is not None
        serialized["worker"] = (request_root / "shared" / "worker-request.json").read_text(encoding="utf-8-sig")
        return parse_result(output)

    monkeypatch.setattr(contained_process, "_write_request", capture_request)
    monkeypatch.setattr(contained_process, "_parse_wrapper_result", capture_worker_request)
    workflow_cleanup.complete_workflow_cleanup(
        tmp_path / "entry",
        tmp_path / "protected",
        "bc-test",
        worker_command=(sys.executable, "-c", "import os; assert os.environ['SystemRoot']; assert os.environ['PATH']"),
    )
    assert set(serialized) == {"private", "worker"}
    for name, secret in secrets.items():
        assert os.environ[name] == secret
    for text in serialized.values():
        environment = json.loads(text)["env"]
        for name, secret in secrets.items():
            assert name not in environment
            assert secret not in text
        assert "BCBENCH_LIFECYCLE_ENTRY_ROOT" not in environment
        assert "CLEANUP_UNRECOGNIZED_ENV" not in environment
        assert environment["PATH"]
        assert environment["SYSTEMROOT"]
        assert environment["TEMP"]
