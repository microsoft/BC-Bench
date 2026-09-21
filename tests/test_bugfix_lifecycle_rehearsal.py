import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from bcbench.dataset import TestEntry
from bcbench.evaluate.bugfix_lifecycle.phases import classify_phase_error
from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalAdapter, RehearsalFault, inject_test_evidence_fault
from bcbench.exceptions import TestExecutionError, TestInfrastructureError
from bcbench.operations.bc_operations import require_test_evidence
from bcbench.operations.test_execution import TestExpectation
from bcbench.results.bugfix import BugFixPhaseStatus

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Production bug-fix rehearsal requires Windows")


def _valid_evidence(directory: Path) -> tuple[TestEntry, ...]:
    tests = (TestEntry(codeunitID=50199, functionName=frozenset({"RehearsalProbe"})),)
    (directory / "discovery-50199.json").write_text(json.dumps({"codeunitID": 50199, "functionName": ["RehearsalProbe"]}), encoding="utf-8")
    (directory / "results-50199.xml").write_text('<testsuite><testcase name="RehearsalProbe"/></testsuite>', encoding="utf-8")
    return tests


@pytest.mark.parametrize("fault", [RehearsalFault.MISSING_JUNIT, RehearsalFault.DUPLICATE_DISCOVERY, RehearsalFault.DUPLICATE_EXECUTION])
def test_fault_changes_real_test_evidence_and_uses_production_classification(tmp_path: Path, fault: RehearsalFault) -> None:
    tests = _valid_evidence(tmp_path)
    discovery = tmp_path / "discovery-50199.json"
    junit = tmp_path / "results-50199.xml"
    require_test_evidence(tmp_path, tests, TestExpectation.ALL_PASS)
    inject_test_evidence_fault(fault, tmp_path, tests)
    with pytest.raises((TestExecutionError, TestInfrastructureError)) as caught:
        require_test_evidence(tmp_path, tests, TestExpectation.ALL_PASS)
    assert classify_phase_error(caught.value) is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    if fault is RehearsalFault.MISSING_JUNIT:
        assert not junit.exists()
    elif fault is RehearsalFault.DUPLICATE_DISCOVERY:
        assert json.loads(discovery.read_text())["functionName"] == ["RehearsalProbe"] * 2
    else:
        assert junit.read_text().count('name="RehearsalProbe"') == 2


def test_evidence_injection_does_not_accept_unrelated_broken_input(tmp_path: Path) -> None:
    with pytest.raises(TestInfrastructureError, match="Invalid test evidence"):
        inject_test_evidence_fault(
            RehearsalFault.DUPLICATE_EXECUTION,
            tmp_path,
            (TestEntry(codeunitID=50199, functionName=frozenset({"RehearsalProbe"})),),
        )


@pytest.mark.parametrize("failure", ["nonzero_exit", "assertion", "malformed", "empty_selection"])
def test_shared_evidence_classifier_preserves_failure_kind(tmp_path: Path, failure: str) -> None:
    tests = _valid_evidence(tmp_path)
    if failure == "assertion":
        (tmp_path / "results-50199.xml").write_text('<testsuite><testcase name="RehearsalProbe"><failure/></testcase></testsuite>', encoding="utf-8")
    elif failure == "malformed":
        (tmp_path / "results-50199.xml").write_text("<invalid", encoding="utf-8")
    elif failure == "empty_selection":
        tests = ()
    with pytest.raises((TestExecutionError, TestInfrastructureError)) as caught:
        require_test_evidence(
            tmp_path,
            tests,
            TestExpectation.ALL_PASS,
            returncode=1 if failure == "nonzero_exit" else 0,
            stdout="fixture stdout",
            stderr="fixture stderr",
        )
    expected = BugFixPhaseStatus.FAILED if failure == "assertion" else BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert classify_phase_error(caught.value) is expected
    assert caught.value.stdout == "fixture stdout"
    assert caught.value.stderr == "fixture stderr"


def test_evidence_injection_refuses_preexisting_test_failure(tmp_path: Path) -> None:
    tests = _valid_evidence(tmp_path)
    junit = tmp_path / "results-50199.xml"
    junit.write_text('<testsuite><testcase name="RehearsalProbe"><failure/></testcase></testsuite>', encoding="utf-8")
    pristine = junit.read_bytes()
    with pytest.raises(TestExecutionError):
        inject_test_evidence_fault(RehearsalFault.MISSING_JUNIT, tmp_path, tests)
    assert junit.read_bytes() == pristine


def test_non_evidence_fault_is_rejected_without_mutation(tmp_path: Path) -> None:
    tests = _valid_evidence(tmp_path)
    pristine = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(ValueError, match="Not a test-evidence fault"):
        inject_test_evidence_fault(RehearsalFault.CORRUPT_BACKUP, tmp_path, tests)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == pristine


def test_public_script_contract_and_parser() -> None:
    root = Path(__file__).parents[1]
    script = root / "scripts" / "Test-BugFixLifecycleCheckpoint.ps1"
    assert script.is_file()
    source = script.read_text()
    for parameter in ("ContainerName", "CheckpointPath", "Iterations", "Fault"):
        assert f"${parameter}" in source
    for fault in RehearsalFault:
        assert f'"{fault.value}"' in source
    assert "Start-BCBenchWorkflowExecution" in source
    assert "Complete-BugFixLifecycle.ps1" in source
    assert "WindowsApps" in source
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell parser unavailable")
    result = subprocess.run(
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"$e=$null; $t=$null; [Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$t,[ref]$e) | Out-Null; if ($e.Count) {{ throw ($e | Out-String) }}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("invalid", [None, "product", "foreign_project", "hash", "version", "missing"])
def test_inventory_mutation_requires_exact_entry_test_publication(tmp_path: Path, invalid: str | None) -> None:
    from bcbench.evaluate.bugfix_lifecycle.evidence import sha256_file
    from bcbench.evaluate.bugfix_lifecycle.models import ProjectPublication
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import select_rehearsal_app
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _app

    package = tmp_path / "test.app"
    package.write_bytes(b"trusted package")
    app = replace(_app(), name="Entry Tests", content_hash=sha256_file(package))
    project = "src/Entry/Tests" if invalid != "product" else "src/Entry/App"
    publication = ProjectPublication((project,), (package,), (app,))
    baseline = (replace(app, version="9.0.0.0"),) if invalid == "version" else (app,)
    if invalid == "hash":
        package.write_bytes(b"tampered")
    if invalid == "missing":
        baseline = ()
    allowed = ("src/Other/Tests",) if invalid == "foreign_project" else (project,)
    if invalid:
        with pytest.raises(CheckpointInfrastructureError):
            select_rehearsal_app(publication, baseline, allowed)
    else:
        assert select_rehearsal_app(publication, baseline, allowed) == app


@pytest.mark.parametrize("field", ["database_files", "columns", "rows", "discovered"])
def test_probe_comparison_rejects_each_restoration_dimension(field: str) -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, require_same_probe
    from bcbench.exceptions import CheckpointInfrastructureError

    original = RehearsalProbe((r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE",), ("MarkerId:int", "Value:int"), ("1:17",), ("50100:Probe",))
    altered = replace(original, **{field: (*getattr(original, field), "extra")})
    with pytest.raises(CheckpointInfrastructureError, match=field):
        require_same_probe(original, altered)


def test_probe_discovery_compares_multisets() -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, require_same_probe
    from bcbench.exceptions import CheckpointInfrastructureError

    probe = RehearsalProbe((r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE",), (), (), ("1:A", "2:B"))
    require_same_probe(probe, replace(probe, discovered=("2:B", "1:A")))
    with pytest.raises(CheckpointInfrastructureError, match="discovered"):
        require_same_probe(probe, replace(probe, discovered=("1:A", "1:A", "2:B")))


def test_rehearsal_workflow_uses_two_entries_and_optional_success_gate() -> None:
    import yaml

    root = Path(__file__).parents[1]
    jobs = yaml.safe_load((root / ".github" / "workflows" / "bugfix-production-evaluation.yml").read_text())["jobs"]
    assert jobs["rehearsal-entries"]["with"] == {"category": "bug-fix", "test-run": True}
    assert "inputs.rehearsal" in jobs["rehearsal-entries"]["if"]
    assert "inputs.rehearsal-only" in jobs["rehearsal-entries"]["if"]
    assert "rehearsal" in jobs["evaluate"]["needs"]
    assert "always()" in jobs["evaluate"]["if"]
    assert "!inputs.rehearsal-only" in jobs["evaluate"]["if"]
    for status in ("success", "skipped"):
        assert f"needs.rehearsal.result == '{status}'" in jobs["evaluate"]["if"]
    steps = jobs["rehearsal"]["steps"]
    run = next(step for step in steps if step.get("id") == "rehearsal")
    assert "-Iterations 10" in run["run"]
    assert any(step.get("uses") == "$/.github/actions/setup-bugfix-lifecycle" for step in steps)
    assert not any("install-agent-harnesses" in step.get("uses", "") for step in steps)
    assert not any("evaluation-results-" in step.get("with", {}).get("name", "") for step in steps)
    evaluate = next(step for step in jobs["evaluate"]["steps"] if step.get("id") == "evaluate")
    assert evaluate["env"]["BCBENCH_LIFECYCLE_REHEARSAL_ITERATIONS"] == "${{ inputs.test-run && '1' || '0' }}"


def test_rehearsal_selects_two_distinct_entries_from_actual_four_entry_output(tmp_path: Path, monkeypatch) -> None:
    import os
    import sys

    import yaml

    from bcbench.commands.dataset import list_entries
    from bcbench.types import EvaluationCategory

    raw_output = tmp_path / "raw-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(raw_output))
    list_entries(category=EvaluationCategory.BUG_FIX, github_output="entries", test_run=True)
    entries = json.loads(raw_output.read_text().split("=", 1)[1])
    assert len(entries) == len(set(entries)) == 4
    root = Path(__file__).parents[1]
    jobs = yaml.safe_load((root / ".github" / "workflows" / "bugfix-production-evaluation.yml").read_text())["jobs"]
    assert "select-rehearsal-entries" in jobs
    selection = jobs["select-rehearsal-entries"]
    assert selection["needs"] == "rehearsal-entries"
    step = next(step for step in selection["steps"] if step.get("id") == "select")
    assert jobs["rehearsal"]["needs"] == "select-rehearsal-entries"
    assert jobs["rehearsal"]["strategy"]["matrix"]["entry"] == "${{ fromJson(needs.select-rehearsal-entries.outputs.entries) }}"
    output = tmp_path / "selected-output"
    for provided in (entries, list(reversed(entries)), [entries[0]] * 4, []):
        output.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "-c", step["run"]],
            env={**os.environ, "ENTRIES": json.dumps(provided), "GITHUB_OUTPUT": str(output)},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if len(set(provided)) < 2:
            assert result.returncode != 0
            assert not output.exists()
        else:
            assert result.returncode == 0, result.stderr
            selected = json.loads(output.read_text().split("=", 1)[1])
            assert selected == sorted(entries)[:2]
            assert len(set(selected)) == 2


@pytest.mark.parametrize("failure", [None, "data", "schema", "inventory", "discovery", "mutate", "interrupt"])
def test_real_checkpoint_manager_restores_sql_fixture_and_stops_on_first_mismatch(tmp_path: Path, failure: str | None) -> None:
    import base64
    import re
    import sqlite3

    from bcbench.evaluate.bugfix_lifecycle import CheckpointManager, EvidenceStore, sha256_file
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, run_checkpoint_rehearsal
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _app, _identity, _paths

    paths = _paths(tmp_path)
    database = tmp_path / "owned.db"
    with sqlite3.connect(database) as connection:
        connection.executescript("CREATE TABLE inventory(installed INT); INSERT INTO inventory VALUES (1);")
    app = _app()
    calls = []

    def inventory():
        with sqlite3.connect(database) as connection:
            return (replace(app, installed=bool(connection.execute("SELECT installed FROM inventory").fetchone()[0])),)

    def runner(script):
        if "Backup-BCBenchCheckpoint" in script:
            staging_match = re.search(r"-StagingDirectory '([^']+)'", script)
            name_match = re.search(r"-Name '([^']+)'", script)
            assert staging_match is not None
            assert name_match is not None
            staging = Path(staging_match.group(1))
            name = name_match.group(1)
            backup = staging / "database.bak"
            backup.write_bytes(database.read_bytes())
            calls.append(f"capture:{name}")
            payload = {
                "name": name,
                "backup_path": str(backup),
                "sha256": sha256_file(backup),
                "database_name": "BC",
                "database_folder": "C:\\databases",
                "container": _identity().to_dict(),
                "apps": [a.to_dict() for a in inventory()],
                "service": {"server_instance": "BC", "previous_process_id": 10, "state": "Stopped"},
            }
        else:
            if "Restore-BCBenchCheckpoint" in script:
                encoded_match = re.search(r"FromBase64String\('([^']+)'\)", script)
                assert encoded_match is not None
                encoded = encoded_match.group(1)
                manifest = json.loads(base64.b64decode(encoded))
                calls.append(f"restore:{manifest['name']}")
                database.write_bytes(Path(manifest["backup_path"]).read_bytes())
                if manifest["name"] != "baseline":
                    with sqlite3.connect(database) as connection:
                        if failure == "data":
                            connection.execute("UPDATE probe SET value=999")
                        elif failure == "schema":
                            connection.execute("ALTER TABLE probe ADD COLUMN leaked INT")
                        elif failure == "inventory":
                            connection.execute("UPDATE inventory SET installed=0")
            payload = {
                "container": _identity().to_dict(),
                "apps": [a.to_dict() for a in inventory()],
                "database_name": "BC",
                "database_folder": "C:\\databases",
                "database_online": True,
                "service_restarted": True,
                "company_endpoint_ready": True,
                "test_discovery_ready": True,
                "test_count": 1,
            }
        return subprocess.CompletedProcess(["fixture"], 0, json.dumps(payload), "")

    manager = CheckpointManager(paths, EvidenceStore(paths), runner, container_name="bc-checkpoint", container_id="container-id", invocation_id="invocation-id", expected_company="CRONUS")
    s0 = manager.capture("baseline", (app,))
    original_hash = sha256_file(s0.backup_path)

    class Adapter:
        probe_name = "BCBenchRehearsal_" + "a" * 32
        fault_applied = False

        def read_probe(self):
            with sqlite3.connect(database) as connection:
                columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(probe)"))
                rows = tuple(str(row[0]) for row in connection.execute("SELECT value FROM probe")) if columns else ()
            discovery = ("50100:Probe",)
            if failure == "discovery" and any(call.startswith("restore:rehearsal-") for call in calls) and columns:
                discovery += discovery
            return RehearsalProbe((r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE",), columns, rows, discovery)

        def read_inventory(self):
            return inventory()

        def create_probe(self):
            calls.append("create")
            with sqlite3.connect(database) as connection:
                connection.executescript("CREATE TABLE probe(value INT); INSERT INTO probe VALUES (17);")

        def mutate(self, selected):
            assert selected == app
            calls.append("mutate")
            with sqlite3.connect(database) as connection:
                connection.executescript("UPDATE inventory SET installed=0; UPDATE probe SET value=29; ALTER TABLE probe ADD COLUMN changed INT;")
            if failure == "mutate":
                raise RuntimeError("partial mutation")
            if failure == "interrupt":
                raise KeyboardInterrupt

        def set_fault(self, fault):
            assert fault is RehearsalFault.NONE

        def test_evidence(self, iteration):
            raise AssertionError("Readiness/restore proof must not run tests")

    output = paths.final_results / "rehearsal"
    if failure:
        with pytest.raises((CheckpointInfrastructureError, RuntimeError, KeyboardInterrupt)):
            run_checkpoint_rehearsal(manager, s0, cast(RehearsalAdapter, Adapter()), app, output, iterations=3)
    else:
        run_checkpoint_rehearsal(manager, s0, cast(RehearsalAdapter, Adapter()), app, output, iterations=3)
    records = [json.loads(path.read_text()) for path in sorted(output.glob("iteration-*.json"))]
    assert len(records) == (1 if failure else 3)
    assert all(record["verified"] is (failure is None) for record in records)
    assert calls.count("mutate") == (1 if failure else 3)
    assert calls[-1] == "restore:baseline"
    assert Adapter().read_probe().columns == ()
    assert inventory() == (app,)
    assert sha256_file(s0.backup_path) == original_hash
    assert json.loads((output / "clean-s0.json").read_text())["verified"] is True
    if failure is None:
        from bcbench.evaluate.bugfix_lifecycle.rehearsal_execution import require_rehearsal_evidence
        from tests.test_bugfix_production_lifecycle import _harness

        request, *_ = _harness(tmp_path / "validation")
        resources = replace(request.provisioned_resources, paths=paths, expected_container_id="container-id")
        require_rehearsal_evidence(resources, 3, RehearsalFault.NONE)
        with pytest.raises(CheckpointInfrastructureError, match="evidence"):
            require_rehearsal_evidence(resources, 10, RehearsalFault.NONE)
        record = output / "iteration-0002.json"
        value = json.loads(record.read_text())
        value["verified"] = False
        record.write_text(json.dumps(value))
        with pytest.raises(CheckpointInfrastructureError, match="evidence"):
            require_rehearsal_evidence(resources, 3, RehearsalFault.NONE)


@pytest.mark.parametrize("case", ["create", "identifier", "ownership", "mutate"])
def test_powershell_probe_boundary_uses_owned_identifiers(tmp_path: Path, case: str) -> None:
    module = Path(__file__).parents[1] / "scripts" / "BugFixLifecycleRehearsal.psm1"
    assert module.exists()
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    script = f"""
Import-Module '{module}' -Force -DisableNameChecking
$script:called = $false
$operations = @{{
    InspectContainer = {{ param($c) [pscustomobject]@{{Exists=$true; Id='{("replacement" if case == "ownership" else "container-id")}'; InvocationId='invocation-id'}} }}
    ReadDatabaseTopology = {{ param($c) [pscustomobject]@{{database_name='BC'; database_folder='C:\\databases'; database_online=$true}} }}
    ExecuteProbe = {{ param($c)
        $script:called = $true
        if ($c.Sql -notmatch 'BCBenchOwner') {{ throw 'No ownership marker check' }}
        if ($c.Sql -match 'DROP TABLE|DELETE FROM') {{ throw 'Destructive fallback' }}
        if ($c.Sql -notmatch 'BCBenchRehearsal_[a-f0-9]{{32}}') {{ throw 'No exact named table' }}
        [pscustomobject]@{{ database_files=@('file'); columns=@(); rows=@() }}
    }}
}}
$failed = $false
try {{
    Invoke-BCBenchRehearsalProbe -ContainerName bc -ExpectedContainerId container-id -ExpectedInvocationId invocation-id `
      -DatabaseName BC -DatabaseFolder 'C:\\databases' -ProbeName '{("Bad;DROP" if case == "identifier" else "BCBenchRehearsal_" + "a" * 32)}' `
      -Mode {("Mutate" if case == "mutate" else "Create")} -Operations $operations | Out-Null
}} catch {{ $failed = $true; [Console]::Error.WriteLine($_.ToString()) }}
@{{failed=$failed;called=$script:called}} | ConvertTo-Json -Compress
"""
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload == {"failed": case in ("identifier", "ownership"), "called": case not in ("identifier", "ownership")}, result.stderr


def test_contained_rehearsal_credentials_are_inherited_not_serialized(tmp_path: Path, monkeypatch) -> None:
    import sys

    from bcbench.agent.shared import contained_process_worker
    from bcbench.agent.shared.contained_process import ContainedProcessRequest, _write_request

    secret = "rehearsal-only-secret-never-json"
    monkeypatch.setenv("BC_SERVER_PASSWORD", secret)
    request = ContainedProcessRequest(
        command=(sys.executable, "-c", "import os; assert os.environ['BC_SERVER_PASSWORD'] == '" + secret + "'"),
        cwd=tmp_path,
        env={},
        timeout_seconds=10,
        parent_environment_keys=("BC_SERVER_PASSWORD",),
    )
    # The command itself must not contain a secret; the child checks its hash.
    import hashlib

    request = replace(
        request, command=(sys.executable, "-c", f"import os,hashlib; assert hashlib.sha256(os.environ['BC_SERVER_PASSWORD'].encode()).hexdigest() == '{hashlib.sha256(secret.encode()).hexdigest()}'")
    )
    path = tmp_path / "request.json"
    _write_request(path, request)
    assert secret not in path.read_text()
    gate = tmp_path / "gate"
    gate.touch()
    assert contained_process_worker.main([str(path), str(gate), "1"]) == 0


def test_active_rehearsal_handoff_blocks_cleanup_and_shutdown(tmp_path: Path) -> None:
    from bcbench.evaluate.bugfix_lifecycle.execution import WorkflowExecution
    from bcbench.exceptions import CleanupInfrastructureError
    from tests.test_bugfix_production_lifecycle import _harness

    request, *_ = _harness(tmp_path)
    execution = WorkflowExecution(request.provisioned_resources)
    execution.path.parent.mkdir(exist_ok=True)
    execution.path.write_text(
        json.dumps(
            {
                "status": "running",
                "container_id": request.expected_container_id,
                "invocation_id": request.expected_container_invocation_id,
            }
        )
    )
    execution.begin_rehearsal()
    with pytest.raises(CleanupInfrastructureError):
        execution.require_shutdown()
    shutdown_calls = []
    with pytest.raises(CleanupInfrastructureError):
        execution.verify_shutdown(lambda: shutdown_calls.append("unsafe-shutdown"))
    assert shutdown_calls == []
    assert json.loads(execution.path.read_text())["status"] == "rehearsal_running"
    execution.finish_rehearsal(resume_lifecycle=True)
    assert json.loads(execution.path.read_text())["status"] == "running"


def test_cleanup_fault_verifier_rejects_unrelated_quarantine(tmp_path: Path) -> None:
    from bcbench.commands.bugfix_rehearsal import verify_cleanup_fault
    from bcbench.exceptions import CleanupInfrastructureError

    (tmp_path / "workflow-setup.json").write_text(json.dumps({"ContainerId": "owned", "ContainerInvocationId": "invocation"}))
    (tmp_path / "workflow-cleanup-worker.json").write_text(json.dumps({"worker_shutdown": "verified"}))
    marker = {"expected_container_id": "owned", "expected_invocation_id": "invocation", "cleanup_errors": ["ownership mismatch"]}
    (tmp_path / "quarantine.json").write_text(json.dumps(marker))
    with pytest.raises(CleanupInfrastructureError):
        verify_cleanup_fault(tmp_path)
    marker["cleanup_errors"] = ["container Docker ID 'owned' still exists after removal."]
    (tmp_path / "quarantine.json").write_text(json.dumps(marker))
    verify_cleanup_fault(tmp_path)
    result = json.loads((tmp_path / "workflow-rehearsal-cleanup-fault.json").read_text())
    assert result["verified"] is True
    assert result["status"] == BugFixPhaseStatus.INFRASTRUCTURE_ERROR.value


@pytest.mark.parametrize(
    ("fault", "expected"),
    [
        ("CorruptBackup", "Staged checkpoint backup hash mismatch"),
        ("ReadinessFailure", "readiness evidence was incomplete"),
        ("UnexpectedApp", "readiness application inventory does not match"),
        ("ServiceRestartFailure", "service tier was not genuinely restarted"),
    ],
)
def test_restore_faults_fail_in_real_production_powershell_validators(tmp_path: Path, fault: str, expected: str) -> None:
    from tests.test_bugfix_lifecycle_checkpoint import _app, _identity

    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    backup = tmp_path / "staging" / "restore" / "database.bak"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b"staged database")
    module = Path(__file__).parents[1] / "scripts" / "BugFixLifecycleRehearsal.psm1"
    script = f"""
$ErrorActionPreference = 'Stop'
Import-Module '{module}' -Force -DisableNameChecking
$global:calls = [Collections.Generic.List[string]]::new()
$identity = '{json.dumps(_identity().to_dict())}' | ConvertFrom-Json
$app = '{json.dumps(_app().to_dict())}' | ConvertFrom-Json
$manifest = [pscustomobject]@{{
    container=$identity; apps=@($app); database_name='BC'; database_folder='C:\\databases';
    backup_path='{backup}'; sha256=(Get-FileHash -LiteralPath '{backup}' -Algorithm SHA256).Hash.ToLowerInvariant()
}}
$ops = @{{
    InspectContainer = {{ [pscustomobject]@{{Exists=$true; Id='container-id'; InvocationId='invocation-id'}} }}
    ReadContainerIdentity = {{ $identity }}
    ReadDatabaseTopology = {{ [pscustomobject]@{{database_name='BC'; database_folder='C:\\databases'; database_online=$true}} }}
    ReadAppInventory = {{ @($app) }}
    StopServiceTier = {{ $global:calls.Add('stop'); [pscustomobject]@{{server_instance='BC';previous_process_id=10;state='Stopped'}} }}
    StartServiceTier = {{ $global:calls.Add('start'); [pscustomobject]@{{restarted=$true}} }}
    RestoreDatabases = {{ $global:calls.Add('restore') }}
    TestReadiness = {{ $global:calls.Add('readiness'); [pscustomobject]@{{company_endpoint_ready=$true;test_discovery_ready=$true;test_count=1}} }}
}}
$message = ''
try {{
    Restore-BCBenchRehearsalCheckpoint -ContainerName bc -ExpectedContainerId container-id -ExpectedInvocationId invocation-id `
      -Manifest $manifest -Credential ([PSCredential]::new('fixture',(ConvertTo-SecureString 'fixture' -AsPlainText -Force))) `
      -ExpectedCompany CRONUS -StagingRoot '{backup.parent.parent}' -Fault {fault} -Operations $ops | Out-Null
}} catch {{ $message=$_.Exception.Message }}
@{{message=$message;calls=@($global:calls)}} | ConvertTo-Json -Compress
"""
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert expected in payload["message"], payload
    assert "readiness" not in payload["calls"]
    assert ("restore" in payload["calls"]) is (fault != "CorruptBackup")


def test_hash_fault_rejects_protected_manifest_without_modifying_master(tmp_path: Path) -> None:
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _manager

    manager, runner, _paths, app = _manager(tmp_path)
    s0 = manager.capture("baseline", (app,))
    original = s0.backup_path.read_bytes()
    runner.calls.clear()
    with pytest.raises(CheckpointInfrastructureError, match="protected checkpoint hash mismatch"):
        manager.restore(replace(s0, sha256="0" * 64), (app,))
    assert s0.backup_path.read_bytes() == original
    assert runner.calls == []


def test_rehearsal_supervisor_does_not_accept_zero_exit_without_cycle_evidence(tmp_path: Path, monkeypatch) -> None:
    from bcbench.agent.shared.contained_process import ContainedProcessResult
    from bcbench.evaluate.bugfix_lifecycle.rehearsal_execution import run_rehearsal_worker
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_production_lifecycle import _harness

    request, *_ = _harness(tmp_path)
    root = request.paths.protected_root
    root.mkdir(exist_ok=True)
    (root / "workflow-execution.json").write_text(
        json.dumps(
            {
                "status": "launching",
                "container_id": request.expected_container_id,
                "invocation_id": request.expected_container_invocation_id,
            }
        )
    )
    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.rehearsal_execution.shutil.which", lambda _: "C:\\PowerShell\\pwsh.exe")

    def child(spec):
        assert json.loads((root / "workflow-execution.json").read_text())["status"] == "rehearsal_running"
        assert "BC_SERVER_PASSWORD" not in spec.env
        assert "BC_SERVER_PASSWORD" in spec.parent_environment_keys
        assert request.evaluator_container.password not in (root / "workflow-rehearsal-request.json").read_text()
        return ContainedProcessResult(0, "", "")

    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.rehearsal_execution.run_contained_process", child)
    with pytest.raises(CheckpointInfrastructureError, match="evidence"):
        run_rehearsal_worker(request.provisioned_resources, request.evaluator_container, request.context.entry, iterations=10)
    assert (root / "quarantine.json").exists()


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
def test_interrupted_rehearsal_worker_never_becomes_never_launched(tmp_path: Path, monkeypatch, failure: str) -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal_execution import run_rehearsal_worker
    from tests.test_bugfix_production_lifecycle import _harness

    request, *_ = _harness(tmp_path)
    root = request.paths.protected_root
    root.mkdir(exist_ok=True)
    (root / "workflow-execution.json").write_text(
        json.dumps(
            {
                "status": "launching",
                "container_id": request.expected_container_id,
                "invocation_id": request.expected_container_invocation_id,
            }
        )
    )
    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.rehearsal_execution.shutil.which", lambda _: "C:\\PowerShell\\pwsh.exe")

    def child(spec):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(spec.command, spec.timeout_seconds)
        raise KeyboardInterrupt

    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.rehearsal_execution.run_contained_process", child)
    with pytest.raises((subprocess.TimeoutExpired, KeyboardInterrupt)):
        run_rehearsal_worker(request.provisioned_resources, request.evaluator_container, request.context.entry, iterations=10)
    assert json.loads((root / "workflow-execution.json").read_text())["status"] == "rehearsal_running"
    assert json.loads((root / "quarantine.json").read_text())["status"] == "quarantined"


def test_timed_out_adapter_refuses_further_container_operations(tmp_path: Path, monkeypatch) -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal_adapter import PowerShellRehearsalAdapter
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _manager
    from tests.test_bugfix_production_lifecycle import _harness

    request, *_ = _harness(tmp_path / "setup")
    manager, _, _, app = _manager(tmp_path / "checkpoint")
    s0 = manager.capture("baseline", (app,))
    adapter = PowerShellRehearsalAdapter(request.provisioned_resources, request.evaluator_container, s0, request.paths.final_results, ())
    calls = []

    def timeout(script):
        calls.append(script)
        raise subprocess.TimeoutExpired(["pwsh"], 1200)

    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.rehearsal_adapter.evaluator_powershell", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        adapter.run("mutate")
    with pytest.raises(CheckpointInfrastructureError, match="unverified"):
        adapter.run("restore")
    assert calls == ["mutate"]


def test_probe_payload_allows_no_tests_during_owned_app_uninstall() -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe

    assert RehearsalProbe.from_dict({"database_files": [r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE"], "columns": ["owned"], "rows": ["1:29"], "discovered": []}).discovered == ()


@pytest.mark.parametrize("keys", [("BC_SERVER_PASSWORD",), ("TOKEN", "token"), ("PATH",)])
def test_parent_environment_channel_cannot_bypass_restricted_identity_or_duplicate_environment(tmp_path: Path, keys) -> None:
    from bcbench.agent.shared.contained_process import ContainedProcessRequest, WindowsIdentity

    with pytest.raises(ValueError, match="environment"):
        ContainedProcessRequest(
            command=("python",),
            cwd=tmp_path,
            env={"PATH": "safe"},
            timeout_seconds=1,
            parent_environment_keys=keys,
            identity=WindowsIdentity("restricted", "secret") if keys == ("BC_SERVER_PASSWORD",) else None,
        )


@pytest.mark.parametrize("methods", [[], ["Probe"], ["Probe", "Probe"]])
def test_powershell_exact_discovery_preserves_flat_multisets(methods) -> None:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    module = Path(__file__).parents[1] / "scripts" / "BugFixLifecycleRehearsal.psm1"
    script = f"""
$ErrorActionPreference='Stop'
Import-Module '{module}' -Force -DisableNameChecking
$ops=@{{
 InspectContainer={{[pscustomobject]@{{Exists=$true;Id='owned';InvocationId='invocation'}}}}
 DiscoverTests={{ [pscustomobject]@{{Id=50100;Tests=('{json.dumps(methods)}'|ConvertFrom-Json)}} }}
}}
$items=@(Get-BCBenchRehearsalDiscovery -ContainerName bc -ExpectedContainerId owned -ExpectedInvocationId invocation `
 -Credential ([PSCredential]::new('fixture',(ConvertTo-SecureString 'fixture' -AsPlainText -Force))) -Company CRONUS -Operations $ops)
@{{discovered=$items}} | ConvertTo-Json -Compress
"""
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, check=False, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["discovered"] == [f"50100:{method}" for method in methods]


def test_lifecycle_finally_preserves_rehearsal_quarantine_resources(tmp_path: Path) -> None:
    from bcbench.evaluate.bugfix_lifecycle.lifecycle import LifecycleCleanup
    from tests.test_bugfix_production_lifecycle import _harness

    request, _lifecycle, calls, _evidence, ownership, _phases = _harness(tmp_path)
    request.paths.protected_root.mkdir(exist_ok=True)
    (request.paths.protected_root / "quarantine.json").write_text('{"reason":"rehearsal_clean_s0_unverified"}')
    error = LifecycleCleanup(request.provisioned_resources, ownership).run()
    assert error is not None
    assert "remove-container" not in calls
    assert "remove-roots" not in calls
    assert "disable-local" in calls


def test_probe_creation_refusal_does_not_restore_over_an_unowned_object(tmp_path: Path) -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, run_checkpoint_rehearsal
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _manager

    manager, runner, paths, app = _manager(tmp_path)
    s0 = manager.capture("baseline", (app,))
    runner.calls.clear()

    class RefusedProbe:
        probe_name = "BCBenchRehearsal_" + "a" * 32
        fault_applied = False

        def read_probe(self):
            return RehearsalProbe((r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE",), (), (), ("50100:Probe",))

        def read_inventory(self):
            return (app,)

        def create_probe(self):
            raise CheckpointInfrastructureError("Refusing an existing SQL probe object")

        def set_fault(self, _fault):
            pass

    with pytest.raises(CheckpointInfrastructureError, match="existing SQL probe"):
        run_checkpoint_rehearsal(manager, s0, cast(RehearsalAdapter, RefusedProbe()), app, paths.final_results / "rehearsal")
    assert runner.calls == []


@pytest.mark.parametrize("fault", [RehearsalFault.MISSING_JUNIT, RehearsalFault.DUPLICATE_DISCOVERY, RehearsalFault.DUPLICATE_EXECUTION])
@pytest.mark.parametrize("attack", [None, "malformed_discovery", "malformed_xml", "wrong_discovery", "unrelated_io", "other_execution"])
def test_injected_evidence_accepts_only_its_specific_production_failure(tmp_path: Path, monkeypatch, fault, attack) -> None:
    from bcbench.evaluate.bugfix_lifecycle import rehearsal as module
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _manager

    manager, _, _, app = _manager(tmp_path)
    manifest = manager.capture("baseline", (app,))
    evidence = tmp_path / "test-evidence"
    evidence.mkdir()
    tests = _valid_evidence(evidence)
    expected = module.RehearsalProbe((r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE",), ("value",), ("17",), ("50199:RehearsalProbe",))

    class Adapter:
        fault_applied = False
        mutated = False

        def mutate(self, selected):
            assert selected == app
            self.mutated = True

        def read_probe(self):
            return replace(expected, columns=("value", "added"), rows=("29",)) if self.mutated else expected

        def read_inventory(self):
            return (replace(app, installed=False),) if self.mutated else (app,)

        def set_fault(self, value):
            assert value is RehearsalFault.NONE

        def test_evidence(self, iteration):
            assert iteration == 1
            return evidence, tests

    adapter = Adapter()
    original_restore = manager.restore

    def restore(*args):
        original_restore(*args)
        adapter.mutated = False

    monkeypatch.setattr(manager, "restore", restore)
    original_inject = module.inject_test_evidence_fault

    def inject(*args):
        proof = original_inject(*args)
        if attack == "malformed_discovery":
            (evidence / "discovery-50199.json").write_text("{invalid", encoding="utf-8")
        elif attack == "malformed_xml":
            (evidence / "results-50199.xml").write_text("<invalid", encoding="utf-8")
        elif attack == "wrong_discovery":
            (evidence / "discovery-50199.json").write_text(json.dumps({"codeunitID": 50199, "functionName": ["Unrelated"]}), encoding="utf-8")
        elif attack == "other_execution":
            # A second requested codeunit disappears only after the target fault was injected.
            (evidence / "results-50200.xml").unlink()
        elif attack == "unrelated_io":

            def failed_read(*_args):
                raise PermissionError("unrelated evidence read failure")

            monkeypatch.setattr("bcbench.operations.bc_operations.load_test_run_summary", failed_read)
        return proof

    if attack == "other_execution":
        tests += (TestEntry(codeunitID=50200, functionName=frozenset({"Other"})),)
        (evidence / "discovery-50200.json").write_text(json.dumps({"codeunitID": 50200, "functionName": ["Other"]}))
        (evidence / "results-50200.xml").write_text('<testsuite><testcase name="Other"/></testsuite>')
    monkeypatch.setattr(module, "inject_test_evidence_fault", inject)
    if attack is None:
        assert module._run_iteration(manager, manifest, cast(RehearsalAdapter, adapter), app, expected, 1, fault, {}) is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    else:
        with pytest.raises((CheckpointInfrastructureError, TestExecutionError, TestInfrastructureError)):
            module._run_iteration(manager, manifest, cast(RehearsalAdapter, adapter), app, expected, 1, fault, {})


@pytest.mark.parametrize(
    "secondary",
    [
        r"BC:2:ROWS:C:\databases\BC2.ndf:OFFLINE",
        r"BC:2:LOG:C:\databases\BC.ldf:RECOVERY_PENDING",
        r"BC:2:LOG:C:\databases\BC.ldf",
        r"BC:2:LOG:C:\databases\BC.ldf:",
        "ONLINE",
    ],
)
def test_every_database_file_must_be_online_even_when_snapshots_are_identical(secondary: str) -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, require_same_probe
    from bcbench.exceptions import CheckpointInfrastructureError

    files = (r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE", secondary)
    payload: dict[str, object] = {"database_files": list(files), "columns": [], "rows": [], "discovered": ["50100:Probe"]}
    with pytest.raises(CheckpointInfrastructureError, match="database_files"):
        RehearsalProbe.from_dict(payload)
    probe = RehearsalProbe(files, (), (), ("50100:Probe",))
    with pytest.raises(CheckpointInfrastructureError, match="database_files"):
        require_same_probe(probe, probe)


def test_persistently_offline_baseline_file_blocks_probe_creation(tmp_path: Path) -> None:
    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, run_checkpoint_rehearsal
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _manager

    manager, runner, paths, app = _manager(tmp_path)
    s0 = manager.capture("baseline", (app,))
    runner.calls.clear()

    class OfflineBaseline:
        def read_probe(self):
            return RehearsalProbe(
                (r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE", r"BC:2:ROWS:C:\databases\BC2.ndf:OFFLINE"),
                (),
                (),
                ("50100:Probe",),
            )

        def read_inventory(self):
            return (app,)

        def create_probe(self):
            pytest.fail("Probe creation must not run with an OFFLINE database file")

    with pytest.raises(CheckpointInfrastructureError, match="database_files"):
        run_checkpoint_rehearsal(manager, s0, cast(RehearsalAdapter, OfflineBaseline()), app, paths.final_results / "rehearsal")
    assert runner.calls == []


@pytest.mark.parametrize("failure", ["timeout", "interrupt"])
def test_test_shutdown_latch(tmp_path: Path, monkeypatch, failure: str) -> None:
    import base64
    import re

    from bcbench.evaluate.bugfix_lifecycle.rehearsal import RehearsalProbe, run_checkpoint_rehearsal
    from bcbench.evaluate.bugfix_lifecycle.rehearsal_adapter import PowerShellRehearsalAdapter
    from bcbench.exceptions import CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import _manager
    from tests.test_bugfix_production_lifecycle import _harness

    manager, runner, paths, app = _manager(tmp_path / "c")
    s0 = manager.capture("baseline", (app,))
    request, *_ = _harness(tmp_path / "setup")
    resources = replace(request.provisioned_resources, paths=paths, expected_container_id=s0.container.container_id)
    output = paths.final_results / "rehearsal"
    adapter = PowerShellRehearsalAdapter(resources, request.evaluator_container, s0, output, (TestEntry(codeunitID=50199, functionName=frozenset({"Probe"})),))
    state = {"probe": False, "mutated": False}
    calls = []

    def powershell(script):
        calls.append("powershell")
        result = runner(script)
        payload = json.loads(result.stdout)
        if "Backup-BCBenchCheckpoint" in script:
            name_match = re.search(r"-Name '([^']+)'", script)
            assert name_match is not None
            payload["name"] = name_match.group(1)
        if "Restore-BCBenchCheckpoint" in script:
            manifest_match = re.search(r"FromBase64String\('([^']+)'\)", script)
            assert manifest_match is not None
            manifest = json.loads(base64.b64decode(manifest_match.group(1)))
            state.update(probe=manifest["name"] != "baseline", mutated=False)
        return subprocess.CompletedProcess(result.args, result.returncode, json.dumps(payload), result.stderr)

    def probe():
        return RehearsalProbe(
            (r"BC:1:ROWS:C:\databases\BC.mdf:ONLINE",),
            ("value", "added") if state["mutated"] else (("value",) if state["probe"] else ()),
            ("29",) if state["mutated"] else (("17",) if state["probe"] else ()),
            ("50199:Probe",),
        )

    monkeypatch.setattr("bcbench.evaluate.bugfix_lifecycle.rehearsal_adapter.evaluator_powershell", powershell)
    manager._powershell_runner = adapter.run
    monkeypatch.setattr(adapter, "read_probe", probe)
    monkeypatch.setattr(adapter, "read_inventory", lambda: (replace(app, installed=not state["mutated"]),))
    monkeypatch.setattr(adapter, "create_probe", lambda: state.update(probe=True))
    monkeypatch.setattr(adapter, "mutate", lambda _app: state.update(mutated=True))

    def failed_test_process(*_args, **_kwargs):
        calls.append("test-failed-before-drain")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(["test-fixture"], 1)
        raise KeyboardInterrupt

    # Exercise the production operation's timeout wrapping, not a synthesized phase status.
    monkeypatch.setattr("bcbench.operations.bc_operations.subprocess.run", failed_test_process)
    with pytest.raises((TestInfrastructureError, KeyboardInterrupt, BaseExceptionGroup)):
        run_checkpoint_rehearsal(manager, s0, adapter, app, output, fault=RehearsalFault.MISSING_JUNIT)
    assert calls[-1] == "test-failed-before-drain"
    assert json.loads((output / "clean-s0.json").read_text())["verified"] is False
    assert (paths.protected_root / "quarantine.json").exists()
    with pytest.raises(CheckpointInfrastructureError, match="shutdown is unverified"):
        PowerShellRehearsalAdapter.create_probe(adapter)


def _supervisor_setup(tmp_path: Path):
    from bcbench.commands.bugfix_lifecycle import _lifecycle_paths
    from tests.test_bugfix_production_lifecycle import _harness

    request, *_ = _harness(tmp_path / "fixture")
    paths = _lifecycle_paths(tmp_path / "owned-entry", tmp_path / "owned-protected")
    paths.agent_workspace.mkdir(parents=True)
    paths.protected_root.mkdir()
    resources = replace(request.provisioned_resources, paths=paths)
    (paths.protected_root / "workflow-execution.json").write_text(
        json.dumps(
            {
                "status": "launching",
                "container_id": resources.expected_container_id,
                "invocation_id": resources.expected_container_invocation_id,
            }
        )
    )
    (paths.protected_root / "workflow-setup.json").write_text(
        json.dumps(
            {
                "Status": "ready",
                "InstanceId": resources.instance_id,
                "ContainerName": resources.container_name,
                "ContainerId": resources.expected_container_id,
                "ContainerInvocationId": resources.expected_container_invocation_id,
                "EntryRoot": str(paths.entry_root),
                "ProtectedRoot": str(paths.protected_root),
                "AgentIdentity": {"Username": resources.agent_os_username, "Sid": resources.agent_os_sid},
                "AgentBcIdentity": {"Username": resources.agent_bc_username},
                "AclTransaction": None,
                "OwnedCompilerHelperRoots": [],
                "SetupCleanupErrors": [],
            }
        )
    )
    return request, resources


def _finalize_twice(resources):
    import os

    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell unavailable")
    module = Path(__file__).parents[1] / "scripts" / "BugFixLifecycle.psm1"
    script = f"""
$ErrorActionPreference='Stop'
Import-Module '{module}' -Force -DisableNameChecking
$global:present=$true
$global:calls=[Collections.Generic.List[string]]::new()
$ops=@{{
 InspectContainer={{[pscustomobject]@{{Exists=$global:present;Id=$env:OWNED_ID;InvocationId=$env:OWNED_INVOCATION}}}}
 InspectContainerById={{[pscustomobject]@{{Exists=$global:present;Id=$env:OWNED_ID;InvocationId=$env:OWNED_INVOCATION}}}}
 ReadAgentIdentity={{[pscustomobject]@{{Sid=$env:OWNED_SID}}}}
 DisableAgentIdentity={{$global:calls.Add('disable')}}
 VerifyAgentIdentityDisabled={{}}
 StopServiceTier={{$global:calls.Add('stop')}}
 RemoveBcIdentity={{$global:calls.Add('bc-user')}}
 RemoveContainer={{$global:calls.Add('remove');$global:present=$false}}
 RemoveAcl={{}}
 RemoveAgentIdentity={{}}
}}
foreach ($attempt in 1..2) {{
 try {{
  Complete-BCBenchBugFixLifecycle -EntryRoot $env:OWNED_ENTRY -ProtectedRoot $env:OWNED_ROOT -ContainerName $env:OWNED_NAME -Operations $ops
 }} catch {{ $global:calls.Add('failed') }}
}}
@{{calls=@($global:calls);present=$global:present}} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
        env={
            **os.environ,
            "OWNED_ID": resources.expected_container_id,
            "OWNED_INVOCATION": resources.expected_container_invocation_id,
            "OWNED_SID": resources.agent_os_sid,
            "OWNED_ENTRY": str(resources.paths.entry_root),
            "OWNED_ROOT": str(resources.paths.protected_root),
            "OWNED_NAME": resources.container_name,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("failure", ["nonzero", "missing_evidence", "cancel_validation"])
def test_crash_before_quarantine_never_authorizes_finalizer(tmp_path: Path, monkeypatch, failure: str) -> None:
    from bcbench.agent.shared.contained_process import ContainedProcessResult
    from bcbench.evaluate.bugfix_lifecycle import rehearsal_execution as module

    class SimulatedCrash(BaseException):
        pass

    request, resources = _supervisor_setup(tmp_path)
    root = resources.paths.protected_root
    with monkeypatch.context() as patch:
        patch.setattr(module.shutil, "which", lambda _: "C:\\PowerShell\\pwsh.exe")
        patch.setattr(module, "run_contained_process", lambda _: ContainedProcessResult(1 if failure == "nonzero" else 0, "", ""))
        if failure == "cancel_validation":

            def interrupt(*_args):
                raise KeyboardInterrupt

            patch.setattr(module, "require_rehearsal_evidence", interrupt)
        write = module.write_rehearsal_record

        def crash_before_marker(path, payload):
            if path == root / "quarantine.json":
                raise SimulatedCrash
            return write(path, payload)

        patch.setattr(module, "write_rehearsal_record", crash_before_marker)
        with pytest.raises(SimulatedCrash):
            module.run_rehearsal_worker(resources, request.evaluator_container, request.context.entry, iterations=10)
    assert not (root / "quarantine.json").exists()
    state_before_finalizer = json.loads((root / "workflow-execution.json").read_text())["status"]
    result = _finalize_twice(resources)
    assert result["present"] is True
    assert "remove" not in result["calls"]
    assert result["calls"].count("failed") == 2
    assert state_before_finalizer == "rehearsal_running"
    assert (root / "quarantine.json").exists()


def test_success_evidence_is_durable_before_cleanup_eligibility(tmp_path: Path, monkeypatch) -> None:
    from bcbench.agent.shared.contained_process import ContainedProcessResult
    from bcbench.evaluate.bugfix_lifecycle import rehearsal_execution as module
    from bcbench.evaluate.bugfix_lifecycle.execution import WorkflowExecution

    request, resources = _supervisor_setup(tmp_path)
    root = resources.paths.protected_root
    validated = []
    with monkeypatch.context() as patch:
        patch.setattr(module.shutil, "which", lambda _: "C:\\PowerShell\\pwsh.exe")
        patch.setattr(module, "run_contained_process", lambda _: ContainedProcessResult(0, "", ""))
        patch.setattr(module, "require_rehearsal_evidence", lambda *_: validated.append(True))
        finish = WorkflowExecution.finish_rehearsal

        def finish_after_proof(self, **kwargs):
            assert validated == [True]
            record = json.loads((root / "workflow-rehearsal.json").read_text())
            assert record["status"] == "success"
            assert record["worker_shutdown"] == "verified"
            finish(self, **kwargs)

        patch.setattr(WorkflowExecution, "finish_rehearsal", finish_after_proof)
        module.run_rehearsal_worker(resources, request.evaluator_container, request.context.entry, iterations=10)
    result = _finalize_twice(resources)
    assert result["present"] is False
    assert result["calls"].count("remove") == 1
    assert "failed" not in result["calls"]
    assert not (root / "quarantine.json").exists()


@pytest.mark.parametrize(
    ("stage", "failure"),
    [
        ("capture", "timeout"),
        ("capture", "interrupt"),
        ("capture", "unverified"),
        ("publication", "timeout"),
        ("publication", "interrupt"),
        ("publication", "unverified"),
        ("capture", "completed_error"),
        ("capture", None),
    ],
)
def test_baseline_guard(tmp_path: Path, monkeypatch, stage: str, failure: str | None) -> None:
    from contextlib import suppress

    from bcbench.agent.shared.contained_process import ContainedProcessInfrastructureError, ContainedProcessResult
    from bcbench.commands import bugfix_rehearsal as command
    from bcbench.evaluate.bugfix_lifecycle import ProductionBugFixLifecycle, sha256_file
    from bcbench.evaluate.bugfix_lifecycle import rehearsal_execution as supervisor
    from bcbench.evaluate.bugfix_lifecycle.phases import DefaultProjectPublisher
    from bcbench.exceptions import BuildTimeoutExpired, CheckpointInfrastructureError
    from tests.test_bugfix_lifecycle_checkpoint import FakePowerShellRunner, _app, _identity
    from tests.test_bugfix_production_lifecycle import FakeWorkspace, _harness

    request, *_ = _harness(tmp_path)
    resources = request.provisioned_resources
    paths = resources.paths
    for directory in (paths.mounted_staging, paths.checkpoints, paths.evidence, paths.final_results):
        directory.mkdir(parents=True, exist_ok=True)
    entry = request.context.entry.model_copy(update={"project_paths": ["src/Tests"]})
    (paths.protected_root / "workflow-execution.json").write_text(
        json.dumps(
            {
                "status": "launching",
                "container_id": resources.expected_container_id,
                "invocation_id": resources.expected_container_invocation_id,
            }
        )
    )
    trace = []
    lifecycles = []
    app = _app(name="Entry Tests", package_id=None)
    runner = FakePowerShellRunner(paths, app, _identity())
    project = paths.baseline_workspace / "src" / "Tests"

    def setup_repo(_entry, _path):
        project.mkdir(parents=True)
        (project / "app.json").write_text(
            json.dumps(
                {
                    "id": app.app_id,
                    "name": app.name,
                    "publisher": app.publisher,
                    "version": app.version,
                }
            )
        )

    class FixtureLifecycle(ProductionBugFixLifecycle):
        def __init__(self, **kwargs):
            super().__init__(
                **kwargs,
                setup_repo=setup_repo,
                copy_problem=lambda *_: None,
                set_runtime=lambda *_: None,
                commit_changes=lambda *_: None,
            )
            self._workspace_builder = FakeWorkspace(paths, trace)
            lifecycles.append(self)

    # Keep the real from_resources factory, baseline publisher, and CheckpointManager.
    monkeypatch.setattr(command, "ProductionBugFixLifecycle", FixtureLifecycle)
    monkeypatch.setattr(supervisor.shutil, "which", lambda _: "C:\\PowerShell\\pwsh.exe")

    def completed(script, payload, code=0):
        return subprocess.CompletedProcess(["fixture"], code, json.dumps(payload), "")

    def subprocess_boundary(args, **_kwargs):
        script = args[-1]
        operation = (
            "publication"
            if "Invoke-AppBuildAndPublish" in script
            else "capture"
            if "Backup-BCBenchCheckpoint" in script
            else "service-recovery"
            if "Start-BCBenchServiceTier" in script
            else "inventory"
            if "Get-BCBenchAppInventory" in script
            else "identity"
        )
        if operation == stage and failure in ("timeout", "interrupt", "unverified"):
            trace.append(f"{stage}-{failure}-drain-unknown")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(["fixture"], 1200)
            if failure == "unverified":
                raise ContainedProcessInfrastructureError(
                    None,
                    child_stdout="",
                    child_stderr="",
                    wrapper_stdout="",
                    wrapper_stderr="",
                    reason="fixture descendant drainage unverified",
                )
            raise KeyboardInterrupt
        trace.append(operation)
        if operation == "publication":
            package = project / "output" / "test.app"
            package.parent.mkdir()
            package.write_bytes(b"published test app fixture")
            runner.app = replace(app, content_hash=sha256_file(package))
            return completed(script, {})
        if operation == "capture" and failure == "completed_error":
            return completed(script, {}, code=1)
        if operation in ("capture", "service-recovery"):
            return runner(script)
        if operation == "inventory":
            return completed(script, [runner.app.to_dict()])
        return completed(script, _identity().to_dict())

    monkeypatch.setattr("bcbench.operations.bc_operations.subprocess.run", subprocess_boundary)

    def cycles(checkpoint, s0, adapter, selected, _output, **_kwargs):
        assert s0.name == "baseline"
        assert s0.backup_path.is_file()
        assert sha256_file(s0.backup_path) == s0.sha256
        assert selected == runner.app
        assert adapter._execution_guard is lifecycles[0]._checkpoint_manager._powershell_runner.__self__
        assert checkpoint._powershell_runner.__self__ is adapter
        trace.append("baseline-ready-for-cycles")

    monkeypatch.setattr(command, "run_checkpoint_rehearsal", cycles)

    def verify_baseline(*_args):
        assert "baseline-ready-for-cycles" in trace

    monkeypatch.setattr(supervisor, "require_rehearsal_evidence", verify_baseline)

    def child(spec):
        try:
            command._worker(Path(spec.command[-1]))
        except (CheckpointInfrastructureError, BuildTimeoutExpired, ContainedProcessInfrastructureError, KeyboardInterrupt, BaseExceptionGroup):
            if failure in ("timeout", "interrupt", "unverified"):

                def late_publication(*_args, **_kwargs):
                    trace.append("late-publication-entered")
                    raise AssertionError("Publication must be blocked before entering its adapter")

                with monkeypatch.context() as patch:
                    patch.setattr(DefaultProjectPublisher, "build_and_publish_with_evidence", late_publication)
                    for operation in (
                        lifecycles[0]._ownership_api.read_app_inventory,
                        lambda: lifecycles[0]._baseline_publisher(paths.baseline_workspace, tuple(entry.project_paths)),
                    ):
                        with suppress(CheckpointInfrastructureError, AssertionError):
                            operation()
            trace.append("outer-descendants-drained")
            return ContainedProcessResult(1, "", "")
        trace.append("outer-descendants-drained")
        return ContainedProcessResult(0, "", "")

    monkeypatch.setattr(supervisor, "run_contained_process", child)
    if failure is None:
        supervisor.run_rehearsal_worker(resources, request.evaluator_container, entry, iterations=1)
        assert trace.count("service-recovery") == 1
        assert "baseline-ready-for-cycles" in trace
        assert not (paths.protected_root / "quarantine.json").exists()
        assert json.loads((paths.protected_root / "workflow-execution.json").read_text())["status"] == "shutdown_verified"
    else:
        with pytest.raises(CheckpointInfrastructureError, match="worker failed"):
            supervisor.run_rehearsal_worker(resources, request.evaluator_container, entry, iterations=1)
        if failure == "completed_error":
            assert trace.count("service-recovery") == 1
        else:
            lost = trace.index(f"{stage}-{failure}-drain-unknown")
            assert trace[lost + 1 :] == ["outer-descendants-drained"]
        assert (paths.protected_root / "quarantine.json").exists()
        assert json.loads((paths.protected_root / "workflow-execution.json").read_text())["status"] == "rehearsal_running"
        assert not (paths.final_results / "rehearsal" / "clean-s0.json").exists()
