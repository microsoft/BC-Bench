from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from bcbench.agent.shared.contained_process import AgentExecutionPolicy, WindowsIdentity
from bcbench.evaluate.bugfix_lifecycle import (
    BugFixLifecyclePaths,
    BugFixLifecycleRequest,
    BugFixProductionLifecycle,
    CheckpointManifest,
    ContainerIdentity,
    SubmissionAnalysis,
    TrustedSource,
    analyze_bugfix_submission,
)
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import AgentError, AgentTimeoutError, CleanupInfrastructureError
from bcbench.results.bugfix import BugFixPhaseResult, BugFixPhaseStatus
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
        self.calls = calls
        self.final_result = None

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
        self.final_result = result
        return self.save_text("final-result.json", "result")

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

    def get_container_identity(self) -> ContainerIdentity:
        self.calls.append("identity")
        return ContainerIdentity("container-id", "image-id", "bc", ())

    def read_app_inventory(self):
        self.calls.append("inventory")
        return ()

    def close_contained_group(self) -> None:
        self.calls.append("close-group")

    def stop_agent_sessions(self) -> None:
        self.calls.append("stop-agent-sessions")

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

    def remove_local_identity(self) -> None:
        self.calls.append("remove-local")

    def remove_roots(self) -> None:
        self.calls.append("remove-roots")

    def quarantine(self, errors: tuple[str, ...]) -> None:
        self.calls.append("quarantine")


class FakePhases:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.statuses = {
            "red": BugFixPhaseStatus.PASSED,
            "gold": BugFixPhaseStatus.PASSED,
            "fix": BugFixPhaseStatus.PASSED,
            "pair": BugFixPhaseStatus.PASSED,
            "benchmark": BugFixPhaseStatus.PASSED,
        }
        self.red_executed = ("50100::Regression",)
        self.sf: CheckpointManifest | None = None

    def _phase(self, name: str) -> BugFixPhaseResult:
        return BugFixPhaseResult(
            status=self.statuses[name],
            executed_tests=self.red_executed if name == "red" else (),
        )

    def run_test_red(self, submission, s0):
        self.calls.append("phase:red")
        return self._phase("red")

    def run_test_gold(self, submission, s0, gold_patch):
        self.calls.append("phase:gold")
        return self._phase("gold")

    def run_fix_build(self, submission, s0):
        self.calls.append("phase:fix")
        result = self._phase("fix")
        return result, self.sf if result.status is BugFixPhaseStatus.PASSED else None

    def run_generated_pair(self, submission, sf, red_result):
        self.calls.append("phase:pair")
        return self._phase("pair")

    def run_benchmark_fix(self, submission, sf, benchmark_patch, benchmark_tests):
        self.calls.append("phase:benchmark")
        return self._phase("benchmark")


def _harness(tmp_path: Path):
    calls: list[str] = []
    paths = _paths(tmp_path)
    context = create_evaluation_context(tmp_path)
    evaluator = ContainerConfig("bc", "admin", "evaluator-secret", "CRONUS")
    runtime = AgentRuntimeConfig(container=ContainerConfig("bc", "agent", "agent-secret", "CRONUS"))
    request = BugFixLifecycleRequest(
        context=context,
        paths=paths,
        evaluator_container=evaluator,
        agent_runtime=runtime,
        agent_execution_policy=AgentExecutionPolicy(
            contain_process_tree=True,
            restricted_identity=WindowsIdentity(
                "bcb-1234567-123456",
                "os-secret",
            ),
        ),
        expected_container_id="container-id",
        expected_container_invocation_id="invocation-id",
        agent_os_username="bcb-1234567-123456",
        agent_bc_username="bca-1234567-123456",
        agent_os_sid="S-1-5-21-1",
    )
    evidence = FakeEvidence(tmp_path, calls)
    workspace = FakeWorkspace(paths, calls)
    checkpoint = FakeCheckpoint(tmp_path, calls)
    ownership = FakeOwnership(calls)
    phases = FakePhases(calls)
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
        "remove-acl",
        "remove-local",
        "remove-roots",
    ]


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


def test_fix_failure_determines_pair_and_benchmark_failed(tmp_path: Path) -> None:
    request, lifecycle, calls, _, _, phases = _harness(tmp_path)
    phases.statuses["fix"] = BugFixPhaseStatus.FAILED

    result = lifecycle.run(request, _agent(calls))

    assert result.fix_build.status is BugFixPhaseStatus.FAILED
    assert result.generated_pair.status is BugFixPhaseStatus.FAILED
    assert result.benchmark_fix.status is BugFixPhaseStatus.FAILED
    assert "phase:pair" not in calls
    assert "phase:benchmark" not in calls


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
    assert calls.index("remove-container") < calls.index("quarantine")
    assert "remove-acl" not in calls
    assert "remove-roots" not in calls


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
    assert "quarantine" in calls
