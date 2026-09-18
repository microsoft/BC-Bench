from __future__ import annotations

import json
import os
import subprocess
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from bcbench.agent.shared.contained_process import AgentExecutionPolicy, ContainedProcessInfrastructureError, WindowsIdentity
from bcbench.evaluate.bugfix_lifecycle import (
    BugFixLifecyclePaths,
    BugFixLifecycleRequest,
    BugFixProductionLifecycle,
    CheckpointManifest,
    CleanupLease,
    ContainerIdentity,
    OwnedLifecycleRoot,
    PowerShellLifecycleOwnershipApi,
    ProductionBugFixLifecycle,
    ProvisionedLifecycleResources,
    SubmissionAnalysis,
    TrustedSource,
    analyze_bugfix_submission,
)
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import (
    AgentError,
    AgentTimeoutError,
    CleanupInfrastructureError,
    GeneratedSubmissionError,
    PhaseExecutionInfrastructureError,
)
from bcbench.results.bugfix import BugFixMetricName, BugFixPhaseResult, BugFixPhaseStatus, BugFixResultSummary
from bcbench.types import AgentMetrics, AgentRuntimeConfig, ContainerConfig, ExperimentConfiguration
from tests.conftest import create_evaluation_context


def _paths(tmp_path: Path) -> BugFixLifecyclePaths:
    entry = tmp_path / "entry"
    protected = tmp_path / "protected"
    return BugFixLifecyclePaths(
        entry_root=entry,
        baseline_workspace=entry / "baseline",
        agent_workspace=entry / "agent",
        agent_logs=entry / "logs",
        agent_tools=entry / "agent-tools",
        mounted_staging=entry / "staging",
        evaluator_workspaces=entry / "evaluators",
        evidence=entry / "evidence",
        protected_root=protected,
        trusted_source=protected / "trusted.git",
        checkpoints=protected / "checkpoints",
        final_results=protected / "final",
    )


def _manifest(tmp_path: Path, name: str) -> CheckpointManifest:
    return CheckpointManifest(
        name=name,
        backup_path=tmp_path / f"{name}.bak",
        sha256=sha256(name.encode()).hexdigest(),
        database_name="BC",
        database_folder=r"C:\database",
        container=ContainerIdentity(
            container_id="container-id",
            image_id="image-id",
            hostname="bc",
            mounts=(),
        ),
        apps=(),
    )


def _submission(*, fix_error: str | None = None, test_error: str | None = None) -> SubmissionAnalysis:
    generated = GeneratedBugFixOutput(
        full_patch="F+T",
        fix_patch="F",
        test_patch="T",
        app_projects=("src/App",),
        test_projects=("src/Tests",),
        tests=(),
    )
    return SubmissionAnalysis(
        submission=generated,
        fix_error=fix_error,
        test_error=test_error,
    )


class FakeEvidence:
    def __init__(self, tmp_path: Path, calls: list[str]) -> None:
        self.root = tmp_path / "protected"
        self.final_root = self.root / "final"
        self.calls = calls
        self.final_result = None
        self.final_result_payloads: list[str] = []
        self.final_result_failure: str | None = None
        self.final_result_attempts = 0

    def save_text(self, name: str, content: str) -> Path:
        self.calls.append(f"evidence:{name}")
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def save_inventory(self, name: str, expected: object, actual: object) -> Path:
        self.calls.append(f"inventory:{name}")
        return self.save_text(f"{name}.json", "inventory")

    def save_submission(self, name: str, content: str) -> Path:
        self.calls.append(f"submission:{name}")
        return self.save_text(name, content)

    def protect_artifact(self, source: Path, kind: str) -> Path:
        self.calls.append(f"protect:{kind}")
        destination = self.root / kind / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        return destination

    def save_phase(self, name: str, result: BugFixPhaseResult) -> Path:
        self.calls.append(f"save-phase:{name}:{result.status.value}")
        return self.save_text(f"{name}.json", result.model_dump_json())

    def save_final_result(self, result: object) -> Path:
        self.calls.append("save-final-result")
        self.final_result_attempts += 1
        if self.final_result_failure == "before" and self.final_result_attempts == 1:
            raise OSError("protected final failed before write")
        self.final_result = result
        content = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result)
        self.final_result_payloads.append(content)
        path = self.final_root / "final-result.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if self.final_result_failure == "after" and self.final_result_attempts == 1:
            raise OSError("protected final failed after write")
        return path

    def relative_protected_path(self, path: Path) -> Path:
        return path.relative_to(self.root)


class FakeWorkspace:
    def __init__(self, paths: BugFixLifecyclePaths, calls: list[str]) -> None:
        self.paths = paths
        self.calls = calls

    def capture_trusted_source(self, baseline: Path) -> TrustedSource:
        self.calls.append("capture-trusted")
        return TrustedSource(self.paths.trusted_source, "a" * 40)

    def create_agent_workspace(self, trusted_source: TrustedSource) -> Path:
        self.calls.append("create-agent")
        self.paths.agent_workspace.mkdir(parents=True, exist_ok=True)
        return self.paths.agent_workspace

    def remove_baseline_workspace(self) -> None:
        self.calls.append("remove-baseline")


class FakeCheckpoint:
    def __init__(self, tmp_path: Path, calls: list[str]) -> None:
        self.calls = calls
        self.s0 = _manifest(tmp_path, "baseline")
        self.sf = _manifest(tmp_path, "fixed")

    def capture(self, name: str, expected_apps: object) -> CheckpointManifest:
        self.calls.append(f"checkpoint:{name}")
        return self.s0 if name == "baseline" else self.sf


class FakeOwnership:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.cleanup_error: Exception | None = None
        self.ownership_error: Exception | None = None
        self.close_error: Exception | None = None
        self.stop_sessions_error: Exception | None = None
        self.root_error: Exception | None = None
        self.acl_error: Exception | None = None
        self.local_error: Exception | None = None

    def get_container_identity(self) -> ContainerIdentity:
        self.calls.append("identity")
        return ContainerIdentity("container-id", "image-id", "bc", ())

    def read_app_inventory(self):
        self.calls.append("inventory")
        return ()

    def close_contained_group(self) -> None:
        self.calls.append("close-group")
        if self.close_error is not None:
            raise self.close_error

    def stop_agent_sessions(self) -> None:
        self.calls.append("stop-agent-sessions")
        if self.stop_sessions_error is not None:
            raise self.stop_sessions_error

    def verify_container_ownership(self) -> None:
        self.calls.append("verify-ownership")
        if self.ownership_error is not None:
            raise self.ownership_error

    def stop_evaluator_processes(self) -> None:
        self.calls.append("stop-evaluator")

    def remove_bc_user(self) -> None:
        self.calls.append("remove-bc-user")

    def remove_container_and_verify(self) -> None:
        self.calls.append("remove-container")
        if self.cleanup_error is not None:
            raise self.cleanup_error

    def remove_acl(self) -> None:
        self.calls.append("remove-acl")
        if self.acl_error is not None:
            raise self.acl_error

    def remove_local_identity(self) -> None:
        self.calls.append("remove-local")
        if self.local_error is not None:
            raise self.local_error

    def remove_roots(self) -> None:
        self.calls.append("remove-roots")
        if self.root_error is not None:
            raise self.root_error

    def disable_local_identity(self) -> None:
        self.calls.append("disable-local")


class FakePhases:
    def __init__(self, calls: list[str], evidence: FakeEvidence) -> None:
        self.calls = calls
        self.evidence = evidence
        self.statuses = {
            "red": BugFixPhaseStatus.PASSED,
            "gold": BugFixPhaseStatus.PASSED,
            "fix": BugFixPhaseStatus.PASSED,
            "pair": BugFixPhaseStatus.PASSED,
            "benchmark": BugFixPhaseStatus.PASSED,
        }
        self.unexpected_phase: str | None = None
        self.red_executed = ("50100::Regression",)
        self.sf: CheckpointManifest | None = None

    def _phase(
        self,
        name: str,
        status: BugFixPhaseStatus | None = None,
    ) -> BugFixPhaseResult:
        return BugFixPhaseResult(
            status=status or self.statuses[name],
            error_message="unexpected phase failure" if status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR else None,
            executed_tests=self.red_executed if name == "red" else (),
        )

    def _fail_if_configured(self, name: str, evidence_name: str) -> None:
        if self.unexpected_phase != name:
            return
        original = RuntimeError(f"{name} exploded")
        result = self._phase(name, BugFixPhaseStatus.INFRASTRUCTURE_ERROR)
        self.evidence.save_phase(evidence_name, result)
        raise PhaseExecutionInfrastructureError(original, result, evidence_name)

    def run_test_red(self, submission, s0):
        self.calls.append("phase:red")
        self._fail_if_configured("red", "test-red")
        return self._phase("red")

    def run_test_gold(self, submission, s0, gold_patch):
        self.calls.append("phase:gold")
        self._fail_if_configured("gold", "test-gold")
        return self._phase("gold")

    def run_fix_build(self, submission, s0):
        self.calls.append("phase:fix")
        self._fail_if_configured("fix", "fix-build")
        result = self._phase("fix")
        return result, self.sf if result.status is BugFixPhaseStatus.PASSED else None

    def run_generated_pair(self, submission, sf, red_result):
        self.calls.append("phase:pair")
        self._fail_if_configured("pair", "generated-pair")
        return self._phase("pair")

    def run_benchmark_fix(self, submission, sf, benchmark_patch, benchmark_tests):
        self.calls.append("phase:benchmark")
        self._fail_if_configured("benchmark", "benchmark-fix")
        return self._phase("benchmark")


def _harness(tmp_path: Path):
    calls: list[str] = []
    paths = _paths(tmp_path)
    agent_profile = paths.agent_logs / "profile"
    agent_roaming = agent_profile / "AppData" / "Roaming"
    agent_local = agent_profile / "AppData" / "Local"
    agent_temp = agent_profile / "temp"
    for path in (agent_roaming, agent_local, agent_temp):
        path.mkdir(parents=True, exist_ok=True)
    paths.agent_tools.mkdir()
    staged_worker = paths.agent_tools / "contained_process_worker.py"
    staged_worker.write_text("print('worker')\n", encoding="utf-8")
    python_base_prefix = tmp_path / "runtime"
    base_python = python_base_prefix / "nested" / "bin" / "python.exe"
    base_python.parent.mkdir(parents=True)
    base_python.write_bytes(b"python")
    resources = ProvisionedLifecycleResources(
        instance_id=create_evaluation_context(tmp_path).entry.instance_id,
        paths=paths,
        container_name="bc",
        expected_container_id="container-id",
        expected_container_invocation_id="invocation-id",
        agent_os_username="bcb-1234567-123456",
        agent_bc_username="bca-1234567-123456",
        agent_os_sid="S-1-5-21-1",
        benchmark_root=Path(__file__).parents[1],
        staged_worker_path=staged_worker,
        base_python=base_python,
        python_base_prefix=python_base_prefix,
        acl_paths=(
            Path(__file__).parents[1],
            paths.entry_root,
            paths.baseline_workspace,
            paths.mounted_staging,
            paths.evaluator_workspaces,
            paths.evidence,
            paths.protected_root,
            paths.agent_workspace,
            paths.agent_logs,
            paths.agent_tools,
            staged_worker,
            python_base_prefix,
            base_python,
        ),
    )
    context = create_evaluation_context(tmp_path)
    evaluator = ContainerConfig("bc", "admin", "evaluator-secret", "CRONUS")
    runtime = AgentRuntimeConfig(container=ContainerConfig("bc", "bca-1234567-123456", "agent-secret", "CRONUS"))
    request = BugFixLifecycleRequest(
        context=context,
        provisioned_resources=resources,
        evaluator_container=evaluator,
        agent_runtime=runtime,
        agent_execution_policy=AgentExecutionPolicy(
            contain_process_tree=True,
            restricted_identity=WindowsIdentity(
                "bcb-1234567-123456",
                "os-secret",
            ),
            allowlist_environment=True,
            environment_overrides={
                "APPDATA": str(agent_roaming),
                "LOCALAPPDATA": str(agent_local),
                "USERPROFILE": str(agent_profile),
                "HOMEDRIVE": agent_profile.drive,
                "HOMEPATH": str(agent_profile)[len(agent_profile.drive) :],
                "TEMP": str(agent_temp),
                "TMP": str(agent_temp),
            },
        ),
    )
    evidence = FakeEvidence(tmp_path, calls)
    workspace = FakeWorkspace(paths, calls)
    checkpoint = FakeCheckpoint(tmp_path, calls)
    ownership = FakeOwnership(calls)
    phases = FakePhases(calls, evidence)
    phases.sf = checkpoint.sf

    def setup_repo(entry, path):
        calls.append("setup-repo")

    def baseline_publish(path, projects):
        calls.append("baseline-build")

    def copy_problem(entry, path):
        calls.append("copy-problem")

    def set_runtime(path, projects):
        calls.append("set-runtime")

    def commit(path, message):
        calls.append("commit-prep")

    def freeze(path, trusted_commit):
        calls.append("freeze")
        return "F+T"

    lifecycle = BugFixProductionLifecycle(
        evidence_store=evidence,
        workspace_builder=workspace,
        checkpoint_manager=checkpoint,
        phase_runner_factory=lambda trusted: phases,
        ownership_api=ownership,
        baseline_publisher=baseline_publish,
        analyzer=lambda repo, patch, trusted, allowed: _submission(),
        setup_repo=setup_repo,
        copy_problem=copy_problem,
        set_runtime=set_runtime,
        commit_changes=commit,
        freeze_submission=freeze,
    )
    return request, lifecycle, calls, evidence, ownership, phases


def _agent(calls: list[str]):
    def run(context, execution_policy):
        calls.append("agent")
        return AgentMetrics(execution_time=1), ExperimentConfiguration()

    return run


@pytest.mark.parametrize(
    ("execution_policy", "message"),
    [
        (
            AgentExecutionPolicy(
                contain_process_tree=False,
                restricted_identity=WindowsIdentity("bcb-1234567-123456", "os-secret"),
                allowlist_environment=True,
            ),
            "contain the process tree",
        ),
        (
            AgentExecutionPolicy(
                contain_process_tree=True,
                restricted_identity=None,
                allowlist_environment=True,
            ),
            "requires a restricted identity",
        ),
        (
            AgentExecutionPolicy(
                contain_process_tree=True,
                restricted_identity=WindowsIdentity("bcb-1234567-123456", "os-secret"),
                allowlist_environment=False,
            ),
            "allowlist the environment",
        ),
    ],
)
def test_request_rejects_invalid_production_execution_policy_before_collaborators(
    tmp_path: Path,
    execution_policy: AgentExecutionPolicy,
    message: str,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)

    with pytest.raises(ValueError, match=message):
        replace(request, agent_execution_policy=execution_policy)

    assert calls == []


def test_request_requires_all_production_profile_environment_overrides_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    policy = replace(
        request.agent_execution_policy,
        environment_overrides={key: value for key, value in request.agent_execution_policy.environment_overrides.items() if key != "APPDATA"},
    )

    with pytest.raises(ValueError, match="profile environment overrides"):
        replace(request, agent_execution_policy=policy)

    assert calls == []


@pytest.mark.parametrize("name", ["USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP"])
@pytest.mark.parametrize("location", ["outside", "evaluator"])
def test_request_rejects_production_profile_paths_outside_agent_logs_before_collaborators(
    tmp_path: Path,
    name: str,
    location: str,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    invalid_root = tmp_path / "outside-profile" if location == "outside" else request.paths.evaluator_workspaces / "profile"
    policy = replace(
        request.agent_execution_policy,
        environment_overrides=request.agent_execution_policy.environment_overrides | {name: str(invalid_root / name.lower())},
    )

    with pytest.raises(ValueError, match="strict descendant of agent_logs"):
        replace(request, agent_execution_policy=policy)

    assert calls == []


def test_request_rejects_noncanonical_production_profile_path_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    profile = request.paths.agent_logs / "profile"
    policy = replace(
        request.agent_execution_policy,
        environment_overrides=request.agent_execution_policy.environment_overrides | {"USERPROFILE": str(profile / ".." / "profile")},
    )

    with pytest.raises(ValueError, match="canonical"):
        replace(request, agent_execution_policy=policy)

    assert calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
def test_request_rejects_reparse_production_profile_path_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    roaming = Path(request.agent_execution_policy.environment_overrides["APPDATA"])
    roaming.rmdir()
    target = tmp_path / "outside-roaming"
    target.mkdir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(roaming), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"Directory junction creation is unavailable: {result.stderr or result.stdout}")

    with pytest.raises(ValueError, match="reparse"):
        replace(request)

    assert calls == []


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HOMEDRIVE", "Z:"),
        ("HOMEPATH", r"\wrong\profile"),
    ],
)
def test_request_rejects_mismatched_windows_home_components_before_collaborators(
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    policy = replace(
        request.agent_execution_policy,
        environment_overrides=request.agent_execution_policy.environment_overrides | {name: value},
    )

    with pytest.raises(ValueError, match="HOMEDRIVE and HOMEPATH"):
        replace(request, agent_execution_policy=policy)

    assert calls == []


def test_request_rejects_restricted_windows_username_mismatch_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    policy = replace(
        request.agent_execution_policy,
        restricted_identity=WindowsIdentity("other-user", "os-secret"),
    )

    with pytest.raises(ValueError, match="restricted identity username must match agent_os_username"):
        replace(request, agent_execution_policy=policy)

    assert calls == []


def test_request_accepts_local_machine_restricted_windows_domain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("COMPUTERNAME", "BCBENCH-HOST")
    request, _, calls, _, _, _ = _harness(tmp_path)
    policy = replace(
        request.agent_execution_policy,
        restricted_identity=WindowsIdentity(request.agent_os_username, "os-secret", "bcbench-host"),
    )

    updated = replace(request, agent_execution_policy=policy)

    assert updated.agent_execution_policy.restricted_identity is policy.restricted_identity
    assert calls == []


@pytest.mark.parametrize("domain", ["CONTOSO", "localhost"])
def test_request_rejects_nonlocal_restricted_windows_domain_before_collaborators(
    tmp_path: Path,
    domain: str,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    policy = replace(
        request.agent_execution_policy,
        restricted_identity=WindowsIdentity(request.agent_os_username, "os-secret", domain),
    )

    with pytest.raises(ValueError, match="local Windows domain"):
        replace(request, agent_execution_policy=policy)

    assert calls == []


def test_request_rejects_agent_runtime_bc_username_mismatch_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    runtime = replace(
        request.agent_runtime,
        container=replace(request.agent_runtime.container, username="other-agent"),
    )

    with pytest.raises(ValueError, match="agent runtime BC username must match agent_bc_username"):
        replace(request, agent_runtime=runtime)

    assert calls == []


def test_request_rejects_shared_evaluator_and_agent_bc_username_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    evaluator = replace(request.evaluator_container, username=f" {request.agent_bc_username.upper()} ")

    with pytest.raises(ValueError, match="Evaluator and agent BC usernames must differ"):
        replace(request, evaluator_container=evaluator)

    assert calls == []


def test_request_rejects_shared_evaluator_and_agent_password_before_collaborators(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    evaluator = replace(
        request.evaluator_container,
        password=request.agent_runtime.container.password,
    )

    with pytest.raises(ValueError, match="Evaluator and agent passwords must differ"):
        replace(request, evaluator_container=evaluator)

    assert calls == []


def test_request_accepts_normalized_case_insensitive_execution_identities(
    tmp_path: Path,
) -> None:
    request, _, calls, _, _, _ = _harness(tmp_path)
    policy = replace(
        request.agent_execution_policy,
        restricted_identity=WindowsIdentity(
            f" {request.agent_os_username.upper()} ",
            "os-secret",
            " . ",
        ),
    )
    runtime = replace(
        request.agent_runtime,
        container=replace(
            request.agent_runtime.container,
            username=f" {request.agent_bc_username.upper()} ",
        ),
    )

    validated = replace(
        request,
        agent_execution_policy=policy,
        agent_runtime=runtime,
    )

    assert validated.agent_execution_policy is policy
    assert validated.agent_runtime is runtime
    assert calls == []


def _init_submission_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "submission"
    (repo / "src" / "App").mkdir(parents=True)
    (repo / "src" / "Tests").mkdir(parents=True)
    (repo / "src" / "App" / "app.json").write_text("{}", encoding="utf-8")
    (repo / "src" / "Tests" / "app.json").write_text("{}", encoding="utf-8")
    (repo / "src" / "App" / "Feature.Codeunit.al").write_text(
        "codeunit 50100 Feature\n{\n}\n",
        encoding="utf-8",
    )
    (repo / "src" / "Tests" / "FeatureTests.Codeunit.al").write_text(
        'codeunit 50101 "Feature Tests"\n{\n}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
    trusted = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, trusted


def _workspace_diff(repo: Path) -> str:
    return subprocess.run(
        ["git", "diff", "--no-ext-diff"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def test_request_is_immutable(tmp_path: Path) -> None:
    request, _, _, _, _, _ = _harness(tmp_path)

    with pytest.raises(FrozenInstanceError):
        request.expected_container_id = "other"  # type: ignore[misc]


def test_submission_analysis_preserves_valid_fix_when_test_is_invalid(tmp_path: Path) -> None:
    repo, trusted = _init_submission_repo(tmp_path)
    (repo / "src" / "App" / "Feature.Codeunit.al").write_text(
        "codeunit 50100 Feature\n{\n    procedure Fixed()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    (repo / "src" / "Tests" / "FeatureTests.Codeunit.al").write_text(
        'codeunit 50101 "Feature Tests"\n{\n    procedure Helper()\n    begin\n    end;\n}\n',
        encoding="utf-8",
    )

    analysis = analyze_bugfix_submission(
        repo,
        _workspace_diff(repo),
        trusted,
        ("src/App",),
    )

    assert analysis.fix_is_safe is True
    assert analysis.submission.fix_patch
    assert analysis.test_is_safe is False


def test_submission_analysis_preserves_valid_test_when_fix_is_invalid(tmp_path: Path) -> None:
    repo, trusted = _init_submission_repo(tmp_path)
    (repo / "src" / "App" / "Feature.Codeunit.al").write_text(
        "codeunit 50100 Feature\n{\n    procedure Fixed()\n    begin\n    end;\n}\n",
        encoding="utf-8",
    )
    (repo / "src" / "Tests" / "FeatureTests.Codeunit.al").write_text(
        ('codeunit 50101 "Feature Tests"\n{\n    [Test]\n    procedure Regression()\n    begin\n    end;\n}\n'),
        encoding="utf-8",
    )

    analysis = analyze_bugfix_submission(
        repo,
        _workspace_diff(repo),
        trusted,
        (),
    )

    assert analysis.fix_is_safe is False
    assert analysis.test_is_safe is True
    assert analysis.submission.tests


def test_success_exact_call_order(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)

    result = lifecycle.run(request, _agent(calls))

    assert result.resolved is True
    assert calls.index("checkpoint:baseline") < calls.index("capture-trusted")
    assert calls.index("capture-trusted") < calls.index("remove-baseline")
    assert calls.index("close-group") < calls.index("freeze")
    assert calls.index("save-final-result") < calls.index("remove-container")
    assert [call for call in calls if call.startswith("phase:")] == [
        "phase:red",
        "phase:gold",
        "phase:fix",
        "phase:pair",
        "phase:benchmark",
    ]
    assert calls[-7:] == [
        "verify-ownership",
        "stop-evaluator",
        "remove-bc-user",
        "remove-container",
        "remove-roots",
        "remove-acl",
        "remove-local",
    ]
    cleanup = json.loads((request.paths.final_results / "cleanup.json").read_text(encoding="utf-8"))
    assert cleanup["status"] == "success"


def test_invalid_test_valid_fix_still_runs_benchmark(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)
    lifecycle._analyzer = lambda repo, patch, trusted, allowed: _submission(test_error="invalid test")

    result = lifecycle.run(request, _agent(calls))

    assert result.test_red.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.test_gold.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.fix_build.status is BugFixPhaseStatus.PASSED
    assert result.generated_pair.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.benchmark_fix.status is BugFixPhaseStatus.PASSED
    assert [call for call in calls if call.startswith("phase:")] == [
        "phase:fix",
        "phase:benchmark",
    ]


def test_wrong_red_still_runs_gold_fix_pair_and_benchmark(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, phases = _harness(tmp_path)
    phases.statuses["red"] = BugFixPhaseStatus.FAILED

    result = lifecycle.run(request, _agent(calls))

    assert result.test_red.status is BugFixPhaseStatus.FAILED
    assert [call for call in calls if call.startswith("phase:")] == [
        "phase:red",
        "phase:gold",
        "phase:fix",
        "phase:pair",
        "phase:benchmark",
    ]


def test_later_s0_phase_runs_after_earlier_infrastructure_error(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, phases = _harness(tmp_path)
    phases.statuses["red"] = BugFixPhaseStatus.INFRASTRUCTURE_ERROR

    lifecycle.run(request, _agent(calls))

    assert calls.index("phase:red") < calls.index("phase:gold") < calls.index("phase:fix")


@pytest.mark.parametrize(
    "fix_status",
    [
        BugFixPhaseStatus.FAILED,
        BugFixPhaseStatus.INFRASTRUCTURE_ERROR,
    ],
)
def test_fix_failure_leaves_unexecuted_pair_and_benchmark_not_run(
    tmp_path: Path,
    fix_status: BugFixPhaseStatus,
) -> None:
    request, lifecycle, calls, _, _, phases = _harness(tmp_path)
    phases.statuses["fix"] = fix_status

    result = lifecycle.run(request, _agent(calls))

    assert result.fix_build.status is fix_status
    assert result.generated_pair.status is BugFixPhaseStatus.NOT_RUN
    assert result.benchmark_fix.status is BugFixPhaseStatus.NOT_RUN
    assert "phase:pair" not in calls
    assert "phase:benchmark" not in calls


def test_structurally_invalid_fix_marks_its_own_unexecuted_consumers_invalid(
    tmp_path: Path,
) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)
    lifecycle._analyzer = lambda repo, patch, trusted, allowed: _submission(fix_error="invalid fix")

    result = lifecycle.run(request, _agent(calls))

    assert result.fix_build.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.generated_pair.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.benchmark_fix.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert "phase:fix" not in calls
    assert "phase:pair" not in calls
    assert "phase:benchmark" not in calls


@pytest.mark.parametrize(
    ("message", "available_patch"),
    [
        ("Cannot safely freeze workspace symbolic link or reparse point: unsafe", None),
        ("Cannot safely freeze unsupported workspace entry: socket", "partial patch"),
        ("Generated submission diff is not valid UTF-8.", None),
    ],
)
def test_freezer_submission_error_is_globally_invalid(
    tmp_path: Path,
    message: str,
    available_patch: str | None,
) -> None:
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    analyzer_calls: list[str] = []
    lifecycle._analyzer = lambda *args: analyzer_calls.append("analyze") or _submission()
    error = GeneratedSubmissionError(message, generated_patch=available_patch)

    def freeze(_path: Path, _trusted_commit: str) -> str:
        calls.append("freeze")
        raise error

    lifecycle._freeze_submission = freeze

    result = lifecycle.run(request, _agent(calls))

    assert analyzer_calls == []
    assert result.output == (available_patch or "")
    assert result.test_red.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.test_gold.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.fix_build.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.generated_pair.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.benchmark_fix.status is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.metric_status(BugFixMetricName.RESOLUTION) is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.infrastructure_failure is False
    assert result.resolved is False
    assert any(call == "evidence:submission-freeze-invalid.txt" for call in calls)
    assert evidence.final_result == result
    if available_patch is not None:
        assert (evidence.root / "generated-full.patch").read_text(encoding="utf-8") == available_patch


def test_freezer_invalid_submission_precedes_timeout_resolution(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)

    def timeout(context, execution_policy):
        calls.append("agent")
        raise AgentTimeoutError(
            "timed out",
            metrics=AgentMetrics(execution_time=10),
            config=ExperimentConfiguration(),
        )

    def freeze(_path: Path, _trusted_commit: str) -> str:
        calls.append("freeze")
        raise GeneratedSubmissionError("Cannot safely freeze unsupported workspace entry: socket")

    lifecycle._freeze_submission = freeze

    result = lifecycle.run(request, timeout)

    assert result.timeout is True
    assert result.metric_status(BugFixMetricName.RESOLUTION) is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.infrastructure_failure is False


@pytest.mark.parametrize(
    ("phase_name", "result_field", "completed_fields"),
    [
        ("red", "test_red", ()),
        ("gold", "test_gold", ("test_red",)),
        ("fix", "fix_build", ("test_red", "test_gold")),
        ("pair", "generated_pair", ("test_red", "test_gold", "fix_build")),
        (
            "benchmark",
            "benchmark_fix",
            ("test_red", "test_gold", "fix_build", "generated_pair"),
        ),
    ],
)
def test_unexpected_phase_error_preserves_saved_result_and_stops_later_phases(
    tmp_path: Path,
    phase_name: str,
    result_field: str,
    completed_fields: tuple[str, ...],
) -> None:
    request, lifecycle, calls, evidence, _, phases = _harness(tmp_path)
    phases.unexpected_phase = phase_name

    with pytest.raises(RuntimeError, match=rf"{phase_name} exploded"):
        lifecycle.run(request, _agent(calls))

    final_result = evidence.final_result
    assert final_result is not None
    assert getattr(final_result, result_field).status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    for field_name in completed_fields:
        assert getattr(final_result, field_name).status is BugFixPhaseStatus.PASSED
    field_order = ("test_red", "test_gold", "fix_build", "generated_pair", "benchmark_fix")
    failing_index = field_order.index(result_field)
    for field_name in field_order[failing_index + 1 :]:
        assert getattr(final_result, field_name).status is BugFixPhaseStatus.NOT_RUN
    evidence_name = {
        "test_red": "test-red",
        "test_gold": "test-gold",
        "fix_build": "fix-build",
        "generated_pair": "generated-pair",
        "benchmark_fix": "benchmark-fix",
    }[result_field]
    assert sum(call.startswith(f"save-phase:{evidence_name}:") for call in calls) == 1
    assert calls.index("save-final-result") < calls.index("remove-container")


def _assert_single_production_result(request: BugFixLifecycleRequest) -> None:
    result_path = request.context.result_dir / f"{request.context.entry.instance_id}.jsonl"
    lines = result_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    result = request.context.category.result_class.model_validate_json(lines[0])
    summary = BugFixResultSummary.from_results([result], run_id="fault")
    assert summary.total == 1


def test_result_retry_after_failure_before_jsonl_is_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    original = lifecycle._write_result_jsonl
    attempts = 0

    def fail_once(path: Path, result: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("jsonl failed before write")
        original(path, result)

    monkeypatch.setattr(lifecycle, "_write_result_jsonl", fail_once)

    with pytest.raises(OSError, match="jsonl failed before write"):
        lifecycle.run(request, _agent(calls))

    assert attempts == 2
    _assert_single_production_result(request)
    assert evidence.final_result is not None


def test_result_retry_after_jsonl_before_protected_final_does_not_duplicate(
    tmp_path: Path,
) -> None:
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    evidence.final_result_failure = "before"

    with pytest.raises(OSError, match="protected final failed before write"):
        lifecycle.run(request, _agent(calls))

    _assert_single_production_result(request)
    assert evidence.final_result_attempts == 2
    assert evidence.final_result is not None


def test_result_retry_after_protected_final_write_is_idempotent(tmp_path: Path) -> None:
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    evidence.final_result_failure = "after"

    with pytest.raises(OSError, match="protected final failed after write"):
        lifecycle.run(request, _agent(calls))

    _assert_single_production_result(request)
    assert evidence.final_result_attempts == 2
    assert evidence.final_result_payloads[0] == evidence.final_result_payloads[1]
    result_path = evidence.final_root / "final-result.json"
    assert json.loads(result_path.read_text(encoding="utf-8")) == evidence.final_result.model_dump(mode="json")


@pytest.mark.parametrize("failure", ["close", "sessions"])
def test_isolation_barrier_failure_never_freezes_analyzes_or_runs_phases(
    tmp_path: Path,
    failure: str,
) -> None:
    request, lifecycle, calls, _, ownership, _ = _harness(tmp_path)
    analyzer_calls: list[str] = []
    lifecycle._analyzer = lambda *args: analyzer_calls.append("analyze") or _submission()
    if failure == "close":
        ownership.close_error = RuntimeError("job group remains active")
    else:
        ownership.stop_sessions_error = RuntimeError("agent sessions remain active")

    result = lifecycle.run(request, _agent(calls))

    assert "freeze" not in calls
    assert analyzer_calls == []
    assert not any(call.startswith("phase:") for call in calls)
    assert result.test_red.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert result.test_gold.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert result.fix_build.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert result.generated_pair.status is BugFixPhaseStatus.NOT_RUN
    assert result.benchmark_fix.status is BugFixPhaseStatus.NOT_RUN
    assert any(call == "evidence:isolation-barrier-failure.json" for call in calls)


def test_replay_analysis_also_requires_isolation_barrier(tmp_path: Path) -> None:
    request, lifecycle, calls, _, ownership, _ = _harness(tmp_path)
    replay = request.paths.protected_root / "replay.patch"
    replay.parent.mkdir(parents=True)
    replay.write_text("F+T", encoding="utf-8")
    request = BugFixLifecycleRequest(**{**request.__dict__, "replay_patch": replay})
    ownership.close_error = RuntimeError("job group verification failed")
    analyzer_calls: list[str] = []
    lifecycle._analyzer = lambda *args: analyzer_calls.append("analyze") or _submission()

    result = lifecycle.run(request, _agent(calls))

    assert analyzer_calls == []
    assert result.execution_mode == "replay"
    assert result.generated_patch_hash is None


def test_managed_clients_stop_before_service_tier_freeze_and_official_phases(tmp_path):
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    clients = Mock()
    clients.stop.side_effect = lambda: calls.append("stop-clients")
    request = replace(request, agent_execution_policy=replace(request.agent_execution_policy, managed_clients=clients))

    lifecycle.run(request, _agent(calls))

    assert calls.index("agent") < calls.index("stop-clients") < calls.index("stop-agent-sessions") < calls.index("freeze") < calls.index("phase:red")
    barrier = json.loads((evidence.root / "10-isolation-barrier.json").read_text())
    assert barrier["operations"]["stop_agent_clients"]["status"] == "verified"
    assert clients.stop.call_count == 2


def test_bridge_shutdown_failure_blocks_official_phases_and_quarantines(tmp_path):
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    clients = Mock()
    clients.stop.side_effect = RuntimeError("bridge remains active")
    request = replace(request, agent_execution_policy=replace(request.agent_execution_policy, managed_clients=clients))

    with pytest.raises(CleanupInfrastructureError, match="bridge remains active"):
        lifecycle.run(request, _agent(calls))

    assert "freeze" not in calls
    assert "stop-agent-sessions" in calls
    assert "remove-roots" not in calls
    assert "disable-local" in calls
    assert not any(call.startswith("phase:") for call in calls)
    assert evidence.final_result.test_red.status is BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    assert (request.paths.protected_root / "quarantine.json").is_file()


@pytest.mark.parametrize("persistence_failure", [None, "before"])
def test_unverified_agent_job_shutdown_blocks_freeze_even_without_bridge_failure(tmp_path, persistence_failure):
    request, lifecycle, calls, evidence, _, _ = _harness(tmp_path)
    evidence.final_result_failure = persistence_failure
    error = ContainedProcessInfrastructureError(30, child_stdout="", child_stderr="", wrapper_stdout="", wrapper_stderr="")

    def failed_agent(context, policy):
        raise error

    with pytest.raises(CleanupInfrastructureError, match="shutdown was not verified"):
        lifecycle.run(request, failed_agent)
    assert "freeze" not in calls
    assert "stop-agent-sessions" in calls
    assert not any(call.startswith("phase:") for call in calls)
    assert evidence.final_result.generated_patch_hash is None
    assert "remove-roots" not in calls
    assert (request.paths.protected_root / "quarantine.json").is_file()


def test_owned_plugin_root_cleanup_preserves_exact_acl_metadata_after_deletion(tmp_path):
    request, _, _, _, _, _ = _harness(tmp_path)
    resources = request.provisioned_resources
    root = resources.paths.agent_tools / "plugins"
    root.mkdir()
    (root / ".bcbench-owned").write_text(resources.expected_container_invocation_id)
    index = resources.acl_paths.index(resources.staged_worker_path) + 1
    resources = replace(resources, cleanup_tool_roots=(root,), acl_paths=(*resources.acl_paths[:index], root, *resources.acl_paths[index:]))
    scripts = []
    api = PowerShellLifecycleOwnershipApi(resources, None, lambda script: scripts.append(script) or subprocess.CompletedProcess([], 0, "", ""))
    api.remove_roots()
    api.remove_acl()
    assert not root.exists()
    assert str(root).replace("\\", "\\\\") in scripts[-1]


def test_timeout_preserves_diagnostics_and_forces_resolution_failure(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)

    def timeout(context, execution_policy):
        calls.append("agent")
        raise AgentTimeoutError(
            "timed out",
            metrics=AgentMetrics(execution_time=10),
            config=ExperimentConfiguration(custom_instructions=True),
            stdout="stdout",
            stderr="stderr",
        )

    result = lifecycle.run(request, timeout)

    assert result.timeout is True
    assert result.resolved is False
    assert result.agent_stdout == "stdout"
    assert result.agent_stderr == "stderr"
    assert result.metrics == AgentMetrics(execution_time=10)
    assert result.fix_build.status is BugFixPhaseStatus.PASSED


def test_agent_error_freezes_result_then_propagates_after_cleanup(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)

    def fail(context, execution_policy):
        calls.append("agent")
        raise AgentError("agent failed")

    with pytest.raises(AgentError, match="agent failed"):
        lifecycle.run(request, fail)

    assert calls.index("freeze") < calls.index("save-final-result")
    assert calls.index("save-final-result") < calls.index("remove-container")


def test_replay_skips_agent_and_still_cleans_up(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)
    replay = request.paths.protected_root / "replay.patch"
    replay.parent.mkdir(parents=True)
    replay.write_text("F+T", encoding="utf-8")
    request = BugFixLifecycleRequest(**{**request.__dict__, "replay_patch": replay})

    result = lifecycle.run(request, _agent(calls))

    assert "agent" not in calls
    assert "freeze" not in calls
    assert result.execution_mode == "replay"
    assert result.timeout is False
    assert "remove-container" in calls


def test_unexpected_exception_persists_emergency_and_cleans_up(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)

    def explode(context, execution_policy):
        calls.append("agent")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        lifecycle.run(request, explode)

    assert any(call == "evidence:lifecycle-emergency.txt" for call in calls)
    assert "remove-container" in calls


def test_cleanup_failure_quarantines_after_result_persistence(tmp_path: Path) -> None:
    request, lifecycle, calls, _, ownership, _ = _harness(tmp_path)
    ownership.cleanup_error = RuntimeError("cannot remove")

    with pytest.raises(CleanupInfrastructureError, match="cannot remove"):
        lifecycle.run(request, _agent(calls))

    assert calls.index("save-final-result") < calls.index("remove-container")
    assert calls.index("remove-container") < calls.index("disable-local")
    assert "remove-acl" not in calls
    assert "remove-roots" not in calls
    assert request.paths.protected_root.joinpath("quarantine.json").is_file()
    assert request.paths.final_results.joinpath("cleanup.json").is_file()
    assert request.paths.final_results.joinpath("final-result.json").is_file()
    assert not request.paths.final_results.joinpath("cleanup-quarantine.json").exists()


def test_agent_created_commits_are_frozen_against_trusted_commit(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, _ = _harness(tmp_path)
    observed: list[str] = []

    def freeze(path: Path, trusted_commit: str) -> str:
        observed.append(trusted_commit)
        calls.append("freeze")
        return "F+T"

    lifecycle._freeze_submission = freeze
    lifecycle.run(request, _agent(calls))

    assert observed == ["a" * 40]


def test_ownership_mismatch_never_attempts_container_cleanup(tmp_path: Path) -> None:
    request, lifecycle, calls, _, ownership, _ = _harness(tmp_path)
    ownership.ownership_error = RuntimeError("ownership mismatch")

    with pytest.raises(CleanupInfrastructureError, match="ownership mismatch"):
        lifecycle.run(request, _agent(calls))

    assert "remove-bc-user" not in calls
    assert "remove-container" not in calls
    assert "disable-local" in calls
    assert request.paths.protected_root.joinpath("quarantine.json").is_file()


def test_cleanup_removes_owned_entry_and_compiler_helper_roots_before_acl_and_identity(
    tmp_path: Path,
) -> None:
    request, _, _, evidence, _, _ = _harness(tmp_path)
    token = request.expected_container_invocation_id
    compiler_root = tmp_path / "compiler-root"
    helper_root = tmp_path / "helper-root"
    for root in (compiler_root, helper_root):
        root.mkdir()
        (root / ".bcbench-owned").write_text(token, encoding="utf-8")
        (root / "payload.txt").write_text("owned", encoding="utf-8")
    request.paths.final_results.mkdir(parents=True)
    request.paths.final_results.joinpath("evidence.json").write_text("protected", encoding="utf-8")
    request = replace(
        request,
        provisioned_resources=replace(
            request.provisioned_resources,
            compiler_helper_roots=(
                OwnedLifecycleRoot(compiler_root, token),
                OwnedLifecycleRoot(helper_root, token),
            ),
        ),
    )
    for path in (
        request.paths.agent_workspace,
        request.paths.agent_logs,
        request.paths.agent_tools,
        request.paths.mounted_staging,
        request.paths.evaluator_workspaces,
        request.paths.evidence,
    ):
        path.mkdir(parents=True, exist_ok=True)
    api = PowerShellLifecycleOwnershipApi(
        request.provisioned_resources,
        evidence,
        lambda script: subprocess.CompletedProcess([], 0, "{}", ""),
    )

    api.remove_roots()

    assert not request.paths.entry_root.exists()
    assert not compiler_root.exists()
    assert not helper_root.exists()
    assert request.paths.protected_root.exists()
    assert request.paths.final_results.joinpath("evidence.json").is_file()


def test_cleanup_root_marker_mismatch_preserves_root(tmp_path: Path) -> None:
    request, _, _, _, _, _ = _harness(tmp_path)
    root = tmp_path / "compiler-root"
    root.mkdir()
    (root / ".bcbench-owned").write_text("wrong-owner", encoding="utf-8")

    with pytest.raises(ValueError, match="ownership marker"):
        replace(
            request,
            provisioned_resources=replace(
                request.provisioned_resources,
                compiler_helper_roots=(OwnedLifecycleRoot(root, request.expected_container_invocation_id),),
            ),
        )

    assert root.exists()


def test_cleanup_lease_transfers_single_cleanup_owner(tmp_path: Path) -> None:
    request, _, _, _, _, _ = _harness(tmp_path)
    calls: list[str] = []
    lease = CleanupLease.for_cli(request.provisioned_resources)

    lease.transfer_to_lifecycle()

    assert lease.is_lifecycle_owner
    assert lease.cleanup_as_cli(lambda: calls.append("cli")) is None
    lease.cleanup_as_lifecycle(lambda: calls.append("lifecycle"))
    with pytest.raises(RuntimeError, match="already released"):
        lease.cleanup_as_lifecycle(lambda: calls.append("duplicate"))

    assert calls == ["lifecycle"]


def test_powershell_cleanup_uses_exported_acl_paths_and_python_prefix(tmp_path: Path) -> None:
    request, _, _, evidence, _, _ = _harness(tmp_path)
    python_prefix = request.python_base_prefix
    python_executable = request.provisioned_resources.base_python
    scripts: list[str] = []

    def run(script: str) -> subprocess.CompletedProcess[str]:
        scripts.append(script)
        return subprocess.CompletedProcess([], 0, "", "")

    api = PowerShellLifecycleOwnershipApi(request.provisioned_resources, evidence, run)

    api.remove_roots()
    api.remove_acl()

    assert len(scripts) == 1
    assert json.dumps([str(path) for path in request.acl_paths]) in scripts[0]
    assert python_prefix in request.acl_paths
    assert python_executable in request.acl_paths
    assert str(python_executable.parent) not in {str(path) for path in request.acl_paths}


def test_production_lifecycle_public_symbol_and_compatibility_alias() -> None:
    assert ProductionBugFixLifecycle is BugFixProductionLifecycle
