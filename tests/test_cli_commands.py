"""Integration tests for CLI commands using Typer's CliRunner."""

import json
import os
import subprocess
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import PropertyMock, patch

import pytest
import typer
from typer.testing import CliRunner

from bcbench.cli import _redteam_group_installed, app
from bcbench.cli_options import resolve_agent_runtime, resolve_evaluation_runtime
from bcbench.commands import bugfix_lifecycle as bugfix_lifecycle_commands
from bcbench.commands import evaluate as evaluate_commands
from bcbench.commands import run as run_commands
from bcbench.dataset import BugFixEntry
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.types import AgentHarness, AgentMetrics, BCalLLMBackend, ContainerConfig, EvaluationCategory
from tests.conftest import (
    create_bugfix_result,
    create_dataset_entry,
    create_dataset_file,
    create_nl2al_entry,
    create_test_entry,
)

runner = CliRunner()


@dataclass(frozen=True)
class LifecycleCliFixture:
    entry: BugFixEntry
    entry_root: Path
    protected_root: Path
    worker: Path
    python: Path
    python_base_prefix: Path
    tool_root: Path
    replay_patch: Path
    owned_root: Path
    evaluator_config: dict[str, str]
    agent_config: dict[str, str]

    def args(self, command: str, *, replay: bool = False) -> list[str]:
        args = [
            "bugfix-lifecycle",
            command,
            self.entry.instance_id,
            "--entry-root",
            str(self.entry_root),
            "--protected-root",
            str(self.protected_root),
            "--dataset-path",
            str(EvaluationCategory.BUG_FIX.dataset_path),
            "--agent-os-username",
            "bcb-1234567-abcdef",
            "--agent-os-password",
            "os-secret",
            "--agent-bc-username",
            self.agent_config["username"],
            "--agent-bc-password",
            self.agent_config["password"],
            "--expected-container-id",
            "container-id",
            "--expected-invocation-id",
            "invocation-id",
            "--staged-worker-path",
            str(self.worker),
            "--staged-worker-sha256",
            bugfix_lifecycle_commands.sha256_file(self.worker),
            "--base-python",
            str(self.python),
            "--python-base-prefix",
            str(self.python_base_prefix),
            "--agent-os-sid",
            "S-1-5-21-123",
            "--acl-paths-json",
            json.dumps([str(path) for path in self.acl_paths]),
            "--cleanup-tool-roots-json",
            json.dumps([str(path) for path in self.tool_roots]),
            "--owned-compiler-helper-root",
            str(self.owned_root),
            "--evaluator-container-config",
            json.dumps(self.evaluator_config),
            "--agent-container-config",
            json.dumps(self.agent_config),
            "--container-name",
            self.evaluator_config["name"],
            "--username",
            self.evaluator_config["username"],
            "--password",
            self.evaluator_config["password"],
            "--server-url",
            self.evaluator_config["server_url"],
            "--server-instance",
            self.evaluator_config["server_instance"],
            "--mcp-url",
            self.evaluator_config["mcp_url"],
            "--company",
            self.evaluator_config["company"],
            "--output-dir",
            str(self.protected_root.parent / "evaluation_results"),
            "--run-id",
            "lifecycle-run",
            "--al-mcp",
            "--al-lsp",
            "--bc-mcp",
        ]
        if replay:
            args.extend(("--replay-patch", str(self.replay_patch)))
        return args

    @property
    def acl_paths(self) -> tuple[Path, ...]:
        return (
            Path(bugfix_lifecycle_commands.__file__).parents[3],
            self.entry_root,
            self.entry_root / "baseline-workspace",
            self.entry_root / "mounted-staging",
            self.entry_root / "evaluator-workspaces",
            self.entry_root / "evidence",
            self.protected_root,
            self.entry_root / "agent-workspace",
            self.entry_root / "agent-logs",
            self.entry_root / "agent-tools",
            self.worker,
            self.tool_root,
            self.plugin_root,
            self.python_base_prefix,
            self.python,
        )

    @property
    def plugin_root(self) -> Path:
        return self.entry_root / "agent-tools" / "plugins"

    @property
    def tool_roots(self) -> tuple[Path, ...]:
        return self.tool_root, self.plugin_root


@pytest.fixture
def lifecycle_cli_fixture(tmp_path: Path) -> LifecycleCliFixture:
    entry = create_dataset_entry()
    entry_root = tmp_path / "entry"
    protected_root = tmp_path / "protected"
    for root in (entry_root, protected_root):
        root.mkdir()
    (entry_root / "agent-logs").mkdir()
    worker = entry_root / "agent-tools" / "contained_process_worker.py"
    worker.parent.mkdir()
    worker.write_text("print('worker')\n", encoding="utf-8")
    plugin_root = worker.parent / "plugins"
    plugin_root.mkdir()
    (plugin_root / ".bcbench-owned").write_text("invocation-id\n", encoding="utf-8")
    python_base_prefix = tmp_path / "runtime"
    python = python_base_prefix / "nested" / "bin" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    tool_root = tmp_path / "tool"
    tool_root.mkdir()
    replay_patch = protected_root / "replay.patch"
    replay_patch.write_text("diff --git a/a.al b/a.al\n", encoding="utf-8")
    owned_root = tmp_path / "compiler"
    owned_root.mkdir()
    (owned_root / ".bcbench-owned").write_text("invocation-id\n", encoding="utf-8")
    evaluator_config = {
        "name": "bc-lifecycle",
        "username": "admin",
        "password": "evaluator-secret",
        "company": "CRONUS",
        "server_url": "http://bc-lifecycle",
        "server_instance": "BC",
        "mcp_url": "https://bc-lifecycle/mcp",
    }
    agent_config = evaluator_config | {
        "username": "bca-1234567-abcdef",
        "password": "bc-secret",
    }
    return LifecycleCliFixture(
        entry=entry,
        entry_root=entry_root,
        protected_root=protected_root,
        worker=worker,
        python=python,
        python_base_prefix=python_base_prefix,
        tool_root=tool_root,
        replay_patch=replay_patch,
        owned_root=owned_root,
        evaluator_config=evaluator_config,
        agent_config=agent_config,
    )


def _without_options(args: list[str], *options: str) -> list[str]:
    filtered: list[str] = []
    index = 0
    while index < len(args):
        if args[index] in options:
            index += 2
            continue
        filtered.append(args[index])
        index += 1
    return filtered


def _create_junction(junction: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        pytest.skip(f"Directory junction creation is unavailable: {result.stderr or result.stdout}")


@patch("bcbench.cli.import_module")
def test_redteam_group_installed_when_sdk_module_imports(import_module):
    assert _redteam_group_installed()
    import_module.assert_called_once_with("azure.ai.evaluation.red_team")


@patch("bcbench.cli.import_module", side_effect=ImportError)
def test_redteam_group_not_installed_when_sdk_module_import_fails(import_module):
    assert not _redteam_group_installed()
    import_module.assert_called_once_with("azure.ai.evaluation.red_team")


@pytest.fixture(autouse=True)
def disable_github_actions(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    # Reset the config singleton to pick up the environment changes
    import bcbench.config

    bcbench.config._config = None


@pytest.fixture
def sample_dataset_file_for_cli(tmp_path):
    entries = [
        create_dataset_entry(
            instance_id="microsoftInternal__NAV-1",
            base_commit="a" * 40,
            project_paths=["App/W1/TestApp/app", "App/W1/TestApp/test"],
            fail_to_pass=[create_test_entry(codeunit_id=12345, function_names={"TestFunction1"})],
        ),
        create_dataset_entry(
            instance_id="microsoftInternal__NAV-2",
            base_commit="b" * 40,
            environment_setup_version="27.0",
            project_paths=["App/W1/AnotherApp/app", "App/W1/AnotherApp/test"],
            fail_to_pass=[create_test_entry(codeunit_id=67890, function_names={"TestFunction2"})],
        ),
        create_dataset_entry(
            instance_id="microsoftInternal__NAV-3",
            base_commit="c" * 40,
            project_paths=["App/W1/ThirdApp/app", "App/W1/ThirdApp/test"],
            fail_to_pass=[create_test_entry(codeunit_id=22222, function_names={"TestFunction3"})],
            pass_to_pass=[create_test_entry(codeunit_id=11111, function_names={"PassingTest"})],
        ),
    ]
    return create_dataset_file(tmp_path, entries)


@pytest.fixture
def sample_results_directory(tmp_path, sample_dataset_file_for_cli):
    run_id = "test_run_123"
    results_dir = tmp_path / run_id
    results_dir.mkdir(parents=True)

    result1 = create_bugfix_result(
        instance_id="microsoftInternal__NAV-1",
        project="W1/TestApp",
        resolved=True,
        metrics=AgentMetrics(execution_time=120.0, prompt_tokens=5000, completion_tokens=1000),
    )
    result1.save(results_dir, f"{result1.instance_id}.jsonl")

    result2 = create_bugfix_result(
        instance_id="microsoftInternal__NAV-2",
        project="W1/AnotherApp",
        resolved=False,
        error_message="Test failed",
        metrics=AgentMetrics(execution_time=80.0, prompt_tokens=3000, completion_tokens=500),
    )
    result2.save(results_dir, f"{result2.instance_id}.jsonl")

    result3 = create_bugfix_result(
        instance_id="microsoftInternal__NAV-3",
        project="W1/ThirdApp",
        resolved=True,
        metrics=AgentMetrics(execution_time=95.0, prompt_tokens=4200, completion_tokens=800),
    )
    result3.save(results_dir, f"{result3.instance_id}.jsonl")

    return tmp_path, run_id, sample_dataset_file_for_cli


def test_evaluate_bcal_records_backend_model_label(tmp_path):
    entry = create_nl2al_entry()
    captured = {}

    class EntryClass:
        @staticmethod
        def load(_dataset_path, entry_id: str):
            assert entry_id == entry.instance_id
            return [entry]

    class Pipeline:
        def execute(self, context, _agent_runner):
            captured["context"] = context

    with (
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=tmp_path / "nl2al.jsonl"),
        patch.object(EvaluationCategory, "entry_class", new_callable=PropertyMock, return_value=EntryClass),
        patch.object(EvaluationCategory, "pipeline", new_callable=PropertyMock, return_value=Pipeline()),
    ):
        evaluate_commands.evaluate_bcal(
            entry_id=entry.instance_id,
            repo_path=tmp_path / "repo",
            output_dir=tmp_path / "results",
            run_id="bcal-run",
            backend=BCalLLMBackend.AZURE_OPENAI,
            endpoint=" https://aoai.example/ ",
            deployment=" gpt-5.2-prod ",
        )

    assert captured["context"].model == "gpt-5.2-prod"


@pytest.fixture
def agent_command_category(tmp_path):
    entry = create_dataset_entry()

    class EntryClass:
        @staticmethod
        def load(_dataset_path, entry_id: str):
            assert entry_id == entry.instance_id
            return [entry]

    class Pipeline:
        def setup_workspace(self, _entry, _repo_path):
            pass

        def execute(self, context, agent_runner):
            agent_runner(context)

    return entry, SimpleNamespace(
        dataset_path=tmp_path / "dataset.jsonl",
        entry_class=EntryClass,
        pipeline=Pipeline(),
        requires_container=False,
    )


@pytest.mark.parametrize(
    ("commands", "command_name", "agent_name", "extra_args"),
    [
        (run_commands, "run_copilot", "run_copilot_agent", {}),
        (run_commands, "run_claude", "run_claude_code", {}),
        (evaluate_commands, "evaluate_copilot", "run_copilot_agent", {"run_id": "test-run"}),
        (evaluate_commands, "evaluate_claude_code", "run_claude_code", {"run_id": "test-run"}),
    ],
)
def test_agent_commands_preserve_requested_mcp_flags(tmp_path, agent_command_category, commands, command_name, agent_name, extra_args):
    entry, category = agent_command_category

    with (
        patch.object(commands, agent_name) as run_agent,
        patch.object(evaluate_commands, "get_copilot_version", return_value="1.2.3"),
        patch.object(evaluate_commands, "get_claude_version", return_value="1.2.3"),
    ):
        getattr(commands, command_name)(
            entry_id=entry.instance_id,
            category=category,
            repo_path=tmp_path / "repo",
            output_dir=tmp_path / "results",
            container_name="bcbench",
            company="CRONUS",
            mcp_url="https://bc.example/mcp",
            al_mcp=True,
            bc_mcp=True,
            **extra_args,
        )

    runtime = run_agent.call_args.kwargs["runtime"]
    assert runtime.al_mcp is True
    assert runtime.bc_mcp is True
    assert runtime.container.name == "bcbench"


def _runtime_options(**overrides):
    options: dict[str, Any] = {
        "container_name": "",
        "username": "",
        "container_password": "",
        "server_url": "",
        "server_instance": "",
        "mcp_url": None,
        "company": "",
        "al_mcp": False,
        "al_lsp": False,
        "bc_mcp": False,
    }
    return options | overrides


def _resolve_runtime(**overrides):
    return resolve_agent_runtime(**_runtime_options(**overrides))


@pytest.mark.parametrize("feature", ["al_mcp", "al_lsp", "bc_mcp"])
def test_agent_features_require_container(feature):
    with pytest.raises(typer.BadParameter, match="container is required"):
        _resolve_runtime(**{feature: True})


def test_container_options_without_name_are_rejected():
    with pytest.raises(typer.BadParameter, match="require --container-name"):
        _resolve_runtime(username="admin")


def test_bc_mcp_requires_mcp_url():
    with pytest.raises(typer.BadParameter, match="MCP URL is required") as error:
        _resolve_runtime(container_name="bcbench", company="CRONUS", bc_mcp=True)

    assert error.value.param_hint == "--mcp-url"


def test_required_evaluation_container_is_resolved_at_boundary():
    with pytest.raises(typer.BadParameter, match="bug-fix category requires a container"):
        resolve_evaluation_runtime(category=EvaluationCategory.BUG_FIX, **_runtime_options())


def test_every_container_requires_company():
    with pytest.raises(typer.BadParameter, match="Company must not be empty") as error:
        _resolve_runtime(container_name="bcbench", bc_mcp=True)

    assert error.value.param_hint == "--company"


def test_al_lsp_accepts_resolved_container():
    runtime = _resolve_runtime(container_name=" bcbench ", company=" CRONUS ", al_lsp=True)

    assert runtime.al_lsp is True
    assert runtime.container.name == "bcbench"
    assert runtime.container.company == "CRONUS"


@pytest.mark.parametrize(
    ("mcp_url", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" https://bc.example/mcp ", "https://bc.example/mcp"),
    ],
)
def test_container_config_normalizes_mcp_url(mcp_url, expected):
    assert ContainerConfig("bcbench", "admin", "secret", "CRONUS", mcp_url=mcp_url).mcp_url == expected


def test_bugfix_lifecycle_help_lists_fixed_category_agent_commands():
    top_level = runner.invoke(app, ["--help"])
    group = runner.invoke(app, ["bugfix-lifecycle", "--help"])
    copilot = runner.invoke(app, ["bugfix-lifecycle", "copilot", "--help"])

    assert top_level.exit_code == 0
    assert "bugfix-lifecycle" in top_level.stdout
    assert group.exit_code == 0
    assert "copilot" in group.stdout
    assert "claude" in group.stdout
    assert "production bug-fix lifecycle" in group.stdout.lower()
    assert copilot.exit_code == 0
    assert "--category" not in copilot.stdout
    assert "evaluator-container-config" not in copilot.stdout
    assert "agent-container-config" not in copilot.stdout


def test_lifecycle_rejects_unowned_plugin_staging_before_agent_or_dataset(lifecycle_cli_fixture):
    (lifecycle_cli_fixture.plugin_root / ".bcbench-owned").write_text("other-invocation")
    with (
        patch.object(BugFixEntry, "load") as load,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", return_value=None) as cleanup,
    ):
        result = runner.invoke(app, lifecycle_cli_fixture.args("copilot"))
    assert result.exit_code != 0
    assert "ownership marker" in result.output
    load.assert_not_called()
    cleanup.assert_called_once()


@pytest.mark.parametrize("command", ["copilot", "claude"])
@pytest.mark.parametrize("source", ["option", "environment"])
def test_lifecycle_loads_exact_setup_dataset_not_default_with_same_id(lifecycle_cli_fixture, command, source):
    captured = {}
    default = create_dataset_entry(project_paths=["default/App"], environment_setup_version="27.0")
    custom = create_dataset_entry(project_paths=["custom/App"], environment_setup_version="28.0", patch="custom gold patch")

    class Lifecycle:
        def run(self, request, _agent_runner, _cleanup_lease):
            captured["entry"] = request.context.entry

    with tempfile.TemporaryDirectory(prefix=".lifecycle-test-", dir=Path(__file__).parents[1] / "dataset") as directory:
        root = Path(directory)
        (root / "default").mkdir()
        (root / "custom").mkdir()
        default_path = create_dataset_file(root / "default", [default])
        custom_path = create_dataset_file(root / "custom", [custom])
        with (
            patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=default_path),
            patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", return_value=Lifecycle()),
            patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
            patch.object(bugfix_lifecycle_commands, "get_claude_version", return_value="1.2.3"),
        ):
            args = _without_options(lifecycle_cli_fixture.args(command), "--dataset-path")
            if source == "option":
                args.extend(("--dataset-path", str(custom_path)))
            result = runner.invoke(app, args, env={"BCBENCH_LIFECYCLE_DATASET_PATH": str(custom_path)})
        assert result.exit_code == 0, result.output
        assert captured["entry"] == custom


@pytest.mark.parametrize("path_kind", ["missing", "agent-readable"])
def test_lifecycle_acquires_cleanup_before_validating_dataset(lifecycle_cli_fixture, path_kind):
    dataset = lifecycle_cli_fixture.entry_root / ("missing.jsonl" if path_kind == "missing" else "agent-logs\\dataset.jsonl")
    if path_kind != "missing":
        create_dataset_file(dataset.parent)
    args = _without_options(lifecycle_cli_fixture.args("copilot"), "--dataset-path")
    with (
        patch.object(BugFixEntry, "load") as load,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", return_value=None) as cleanup,
    ):
        result = runner.invoke(app, [*args, "--dataset-path", str(dataset)])
    assert result.exit_code != 0
    load.assert_not_called()
    cleanup.assert_called_once()


@pytest.mark.skipif(os.name != "nt", reason="Windows device path parser regression")
@pytest.mark.parametrize("command", ["copilot", "claude"])
@pytest.mark.parametrize("source", ["option", "environment"])
@pytest.mark.parametrize("malformed_ownership", [False, True])
def test_lifecycle_unreadable_device_dataset_reaches_cleanup_ownership(lifecycle_cli_fixture, command, source, malformed_ownership):
    dataset = r"\\.\NUL"
    args = _without_options(lifecycle_cli_fixture.args(command), "--dataset-path")
    if source == "option":
        args.extend(("--dataset-path", dataset))
    if malformed_ownership:
        args[args.index("--acl-paths-json") + 1] = "{"
    raw_cleanup = bugfix_lifecycle_commands.RawSetupCleanup.run
    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True, return_value=None) as cleanup,
        patch.object(bugfix_lifecycle_commands.RawSetupCleanup, "run", autospec=True, side_effect=raw_cleanup) as quarantine,
    ):
        result = runner.invoke(app, args, env={"BCBENCH_LIFECYCLE_DATASET_PATH": dataset})

    assert result.exit_code != 0
    if malformed_ownership:
        quarantine.assert_called_once()
        cleanup.assert_not_called()
        evidence = json.loads((lifecycle_cli_fixture.protected_root / "quarantine.json").read_text())
        assert evidence["status"] == "quarantined"
        assert evidence["reason"] == "ownership_envelope_parse_failure"
    else:
        cleanup.assert_called_once()
        quarantine.assert_not_called()
    assert "not readable" not in result.output
    load_entry.assert_not_called()
    lifecycle_factory.assert_not_called()


def test_lifecycle_cleans_up_after_exact_dataset_loading_fails(lifecycle_cli_fixture):
    with (
        patch.object(BugFixEntry, "load", side_effect=ValueError("invalid custom dataset")),
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", return_value=None) as cleanup,
        patch.object(bugfix_lifecycle_commands, "get_copilot_version") as version,
    ):
        result = runner.invoke(app, lifecycle_cli_fixture.args("copilot"))
    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)
    cleanup.assert_called_once()
    version.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows dataset junction regression")
def test_lifecycle_rejects_dataset_junction_before_loading(lifecycle_cli_fixture):
    dataset = EvaluationCategory.BUG_FIX.dataset_path
    with tempfile.TemporaryDirectory(prefix=".lifecycle-test-", dir=dataset.parent) as directory:
        alias = Path(directory) / "alias"
        _create_junction(alias, dataset.parent)
        try:
            args = _without_options(lifecycle_cli_fixture.args("copilot"), "--dataset-path")
            with (
                patch.object(BugFixEntry, "load") as load,
                patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", return_value=None) as cleanup,
            ):
                result = runner.invoke(app, [*args, "--dataset-path", str(alias / dataset.name)])
            assert result.exit_code != 0
            assert "reparse point" in result.output
            load.assert_not_called()
            cleanup.assert_called_once()
        finally:
            alias.rmdir()


def test_bugfix_lifecycle_requires_protected_root_when_entry_root_is_supplied(
    lifecycle_cli_fixture: LifecycleCliFixture,
):
    result = runner.invoke(
        app,
        [
            "bugfix-lifecycle",
            "copilot",
            lifecycle_cli_fixture.entry.instance_id,
            "--entry-root",
            str(lifecycle_cli_fixture.entry_root),
        ],
        env={"BCBENCH_LIFECYCLE_PROTECTED_ROOT": None},
    )

    assert result.exit_code != 0
    assert "protected-root" in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    ("command", "agent_name", "default_model", "version_function", "runner_function"),
    [
        ("copilot", AgentHarness.COPILOT, "gpt-5.6-luna", "get_copilot_version", "run_copilot_agent"),
        ("claude", AgentHarness.CLAUDE, "claude-haiku-4-5", "get_claude_version", "run_claude_code"),
    ],
)
def test_bugfix_lifecycle_composes_production_request_and_agent_runner(
    lifecycle_cli_fixture: LifecycleCliFixture,
    command: str,
    agent_name: AgentHarness,
    default_model: str,
    version_function: str,
    runner_function: str,
):
    captured: dict[str, Any] = {}

    class Lifecycle:
        def run(self, request, agent_runner, cleanup_lease):
            captured["request"] = request
            captured["runner"] = agent_runner
            captured["cleanup_lease"] = cleanup_lease
            agent_runner(request.context, request.agent_execution_policy)

    def from_request(request):
        captured["constructed_request"] = request
        return Lifecycle()

    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", side_effect=from_request),
        patch.object(bugfix_lifecycle_commands, version_function, return_value="1.2.3"),
        patch.object(bugfix_lifecycle_commands, runner_function) as run_agent,
    ):
        result = runner.invoke(app, lifecycle_cli_fixture.args(command))

    assert result.exit_code == 0, result.stdout
    request = captured["request"]
    assert captured["constructed_request"] is request
    assert captured["cleanup_lease"].is_lifecycle_owner
    assert request.context.category is EvaluationCategory.BUG_FIX
    assert request.context.agent_name is agent_name
    assert request.context.agent_version == "1.2.3"
    assert request.context.model == default_model
    assert request.context.result_dir == lifecycle_cli_fixture.protected_root.parent / "evaluation_results" / "lifecycle-run"
    assert request.context.result_dir != request.paths.agent_logs
    assert request.paths.baseline_workspace == lifecycle_cli_fixture.entry_root / "baseline-workspace"
    assert request.paths.final_results == lifecycle_cli_fixture.protected_root / "final-results"
    assert request.evaluator_container == bugfix_lifecycle_commands.ContainerConfig(**lifecycle_cli_fixture.evaluator_config)
    assert request.agent_runtime.container == bugfix_lifecycle_commands.ContainerConfig(**lifecycle_cli_fixture.agent_config)
    assert request.agent_runtime.al_mcp is True
    assert request.agent_runtime.al_lsp is True
    assert request.agent_runtime.bc_mcp is True
    assert request.agent_execution_policy.contain_process_tree is True
    assert request.agent_execution_policy.allowlist_environment is True
    assert request.agent_execution_policy.python_executable == lifecycle_cli_fixture.python
    assert request.python_base_prefix == lifecycle_cli_fixture.python_base_prefix
    assert request.acl_paths == lifecycle_cli_fixture.acl_paths
    assert request.agent_execution_policy.worker_path == lifecycle_cli_fixture.worker
    assert request.agent_execution_policy.plugin_root == lifecycle_cli_fixture.plugin_root
    agent_profile = request.paths.agent_logs / "profile"
    agent_roaming = agent_profile / "AppData" / "Roaming"
    agent_local = agent_profile / "AppData" / "Local"
    agent_temp = agent_profile / "temp"
    assert request.agent_execution_policy.environment_overrides == {
        "APPDATA": str(agent_roaming),
        "LOCALAPPDATA": str(agent_local),
        "USERPROFILE": str(agent_profile),
        "HOMEDRIVE": agent_profile.drive,
        "HOMEPATH": str(agent_profile)[len(agent_profile.drive) :],
        "TEMP": str(agent_temp),
        "TMP": str(agent_temp),
    }
    assert all(path.is_dir() for path in (agent_profile, agent_roaming, agent_local, agent_temp))
    assert request.compiler_helper_roots[0].path == lifecycle_cli_fixture.owned_root
    run_agent.assert_called_once()
    assert run_agent.call_args.kwargs["category"] is EvaluationCategory.BUG_FIX
    assert run_agent.call_args.kwargs["output_dir"] == request.paths.agent_logs
    assert run_agent.call_args.kwargs["runtime"] is request.agent_runtime
    assert run_agent.call_args.kwargs["execution_policy"] is request.agent_execution_policy


def test_bugfix_lifecycle_replay_skips_agent_runner_and_hides_secrets(lifecycle_cli_fixture: LifecycleCliFixture):
    captured: dict[str, Any] = {}

    class Lifecycle:
        def run(self, request, agent_runner, _cleanup_lease):
            captured["request"] = request
            if request.replay_patch is None:
                agent_runner(request.context, request.agent_execution_policy)

    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", return_value=Lifecycle()),
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
        patch.object(bugfix_lifecycle_commands, "run_copilot_agent") as run_agent,
    ):
        result = runner.invoke(app, ["--verbose", *lifecycle_cli_fixture.args("copilot", replay=True)])

    assert result.exit_code == 0, result.stdout
    assert captured["request"].replay_patch == lifecycle_cli_fixture.replay_patch
    run_agent.assert_not_called()
    for secret in ("os-secret", "bc-secret", "evaluator-secret"):
        assert secret not in result.stdout
        assert secret not in result.stderr


@pytest.mark.parametrize("mcp_env", [None, ""])
def test_bugfix_lifecycle_environment_only_accepts_blank_mcp_url_when_bc_mcp_disabled(
    lifecycle_cli_fixture: LifecycleCliFixture,
    mcp_env: str | None,
):
    captured: dict[str, Any] = {}
    evaluator_config = lifecycle_cli_fixture.evaluator_config | {"mcp_url": ""}
    agent_config = lifecycle_cli_fixture.agent_config | {"mcp_url": ""}

    class Lifecycle:
        def run(self, request, _agent_runner, _cleanup_lease):
            captured["request"] = request

    environment = {
        "BCBENCH_LIFECYCLE_ENTRY_ROOT": str(lifecycle_cli_fixture.entry_root),
        "BCBENCH_LIFECYCLE_PROTECTED_ROOT": str(lifecycle_cli_fixture.protected_root),
        "BCBENCH_LIFECYCLE_DATASET_PATH": str(EvaluationCategory.BUG_FIX.dataset_path),
        "BCBENCH_LIFECYCLE_AGENT_OS_USERNAME": "bcb-1234567-abcdef",
        "BCBENCH_LIFECYCLE_AGENT_OS_PASSWORD": "os-secret",
        "BCBENCH_LIFECYCLE_AGENT_BC_USERNAME": agent_config["username"],
        "BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD": agent_config["password"],
        "BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID": "container-id",
        "BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID": "invocation-id",
        "BCBENCH_LIFECYCLE_STAGED_WORKER_PATH": str(lifecycle_cli_fixture.worker),
        "BCBENCH_LIFECYCLE_STAGED_WORKER_SHA256": bugfix_lifecycle_commands.sha256_file(lifecycle_cli_fixture.worker),
        "BCBENCH_LIFECYCLE_BASE_PYTHON": str(lifecycle_cli_fixture.python),
        "BCBENCH_LIFECYCLE_PYTHON_BASE_PREFIX": str(lifecycle_cli_fixture.python_base_prefix),
        "BCBENCH_LIFECYCLE_AGENT_OS_SID": "S-1-5-21-123",
        "BCBENCH_LIFECYCLE_ACL_PATHS_JSON": json.dumps([str(path) for path in lifecycle_cli_fixture.acl_paths]),
        "BCBENCH_LIFECYCLE_CLEANUP_TOOL_ROOTS_JSON": json.dumps([str(path) for path in lifecycle_cli_fixture.tool_roots]),
        "BCBENCH_LIFECYCLE_OWNED_COMPILER_HELPER_ROOTS": str(lifecycle_cli_fixture.owned_root),
        "BCBENCH_LIFECYCLE_EVALUATOR_CONTAINER_CONFIG": json.dumps(evaluator_config),
        "BCBENCH_LIFECYCLE_AGENT_CONTAINER_CONFIG": json.dumps(agent_config),
        "BC_CONTAINER_NAME": evaluator_config["name"],
        "BC_SERVER_USERNAME": evaluator_config["username"],
        "BC_SERVER_PASSWORD": evaluator_config["password"],
        "BC_SERVER_URL": evaluator_config["server_url"],
        "BC_SERVER_INSTANCE": evaluator_config["server_instance"],
        "BC_COMPANY": evaluator_config["company"],
    }
    if mcp_env is not None:
        environment["BC_MCP_URL"] = mcp_env

    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", return_value=Lifecycle()),
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
    ):
        result = runner.invoke(
            app,
            [
                "--verbose",
                "bugfix-lifecycle",
                "copilot",
                lifecycle_cli_fixture.entry.instance_id,
                "--output-dir",
                str(lifecycle_cli_fixture.protected_root.parent / "evaluation_results"),
                "--run-id",
                "environment-run",
            ],
            env=environment,
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    request = captured["request"]
    assert request.evaluator_container.mcp_url is None
    assert request.agent_runtime.container.mcp_url is None
    assert request.agent_runtime.bc_mcp is False
    for secret in ("os-secret", "bc-secret", "evaluator-secret"):
        assert secret not in result.stdout
        assert secret not in result.stderr


def test_bugfix_lifecycle_constructs_separate_configs_without_json(lifecycle_cli_fixture: LifecycleCliFixture):
    captured: dict[str, Any] = {}

    class Lifecycle:
        def run(self, request, _agent_runner, _cleanup_lease):
            captured["request"] = request

    args = _without_options(
        lifecycle_cli_fixture.args("copilot"),
        "--evaluator-container-config",
        "--agent-container-config",
    )
    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", return_value=Lifecycle()),
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 0, result.stdout + result.stderr
    request = captured["request"]
    assert request.evaluator_container.username == lifecycle_cli_fixture.evaluator_config["username"]
    assert request.agent_runtime.container.username == lifecycle_cli_fixture.agent_config["username"]
    assert request.evaluator_container.password != request.agent_runtime.container.password


def test_bugfix_lifecycle_accepts_prefixed_environment_options(lifecycle_cli_fixture: LifecycleCliFixture):
    captured: dict[str, Any] = {}

    class Lifecycle:
        def run(self, request, _agent_runner, _cleanup_lease):
            captured["request"] = request

    environment = {
        "BCBENCH_LIFECYCLE_ENTRY_ROOT": str(lifecycle_cli_fixture.entry_root),
        "BCBENCH_LIFECYCLE_PROTECTED_ROOT": str(lifecycle_cli_fixture.protected_root),
        "BCBENCH_LIFECYCLE_DATASET_PATH": str(EvaluationCategory.BUG_FIX.dataset_path),
        "BCBENCH_LIFECYCLE_AGENT_OS_USERNAME": "bcb-1234567-abcdef",
        "BCBENCH_LIFECYCLE_AGENT_OS_PASSWORD": "os-secret",
        "BCBENCH_LIFECYCLE_AGENT_BC_USERNAME": lifecycle_cli_fixture.agent_config["username"],
        "BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD": lifecycle_cli_fixture.agent_config["password"],
        "BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID": "container-id",
        "BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID": "invocation-id",
        "BCBENCH_LIFECYCLE_STAGED_WORKER_PATH": str(lifecycle_cli_fixture.worker),
        "BCBENCH_LIFECYCLE_STAGED_WORKER_SHA256": bugfix_lifecycle_commands.sha256_file(lifecycle_cli_fixture.worker),
        "BCBENCH_LIFECYCLE_BASE_PYTHON": str(lifecycle_cli_fixture.python),
        "BCBENCH_LIFECYCLE_PYTHON_BASE_PREFIX": str(lifecycle_cli_fixture.python_base_prefix),
        "BCBENCH_LIFECYCLE_AGENT_OS_SID": "S-1-5-21-123",
        "BCBENCH_LIFECYCLE_ACL_PATHS_JSON": json.dumps([str(path) for path in lifecycle_cli_fixture.acl_paths]),
        "BCBENCH_LIFECYCLE_CLEANUP_TOOL_ROOTS_JSON": json.dumps([str(path) for path in lifecycle_cli_fixture.tool_roots]),
        "BCBENCH_LIFECYCLE_OWNED_COMPILER_HELPER_ROOTS": str(lifecycle_cli_fixture.owned_root),
        "BCBENCH_LIFECYCLE_EVALUATOR_CONTAINER_CONFIG": json.dumps(lifecycle_cli_fixture.evaluator_config),
        "BCBENCH_LIFECYCLE_AGENT_CONTAINER_CONFIG": json.dumps(lifecycle_cli_fixture.agent_config),
        "BCBENCH_LIFECYCLE_AL_MCP": "1",
        "BCBENCH_LIFECYCLE_AL_LSP": "1",
        "BCBENCH_LIFECYCLE_BC_MCP": "1",
        "BC_CONTAINER_NAME": lifecycle_cli_fixture.evaluator_config["name"],
        "BC_SERVER_USERNAME": lifecycle_cli_fixture.evaluator_config["username"],
        "BC_SERVER_PASSWORD": lifecycle_cli_fixture.evaluator_config["password"],
        "BC_SERVER_URL": lifecycle_cli_fixture.evaluator_config["server_url"],
        "BC_SERVER_INSTANCE": lifecycle_cli_fixture.evaluator_config["server_instance"],
        "BC_MCP_URL": lifecycle_cli_fixture.evaluator_config["mcp_url"],
        "BC_COMPANY": lifecycle_cli_fixture.evaluator_config["company"],
    }
    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", return_value=Lifecycle()),
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
    ):
        result = runner.invoke(
            app,
            [
                "bugfix-lifecycle",
                "copilot",
                lifecycle_cli_fixture.entry.instance_id,
                "--output-dir",
                str(lifecycle_cli_fixture.protected_root.parent / "evaluation_results"),
                "--run-id",
                "environment-run",
            ],
            env=environment,
        )

    assert result.exit_code == 0, result.stdout + result.stderr
    request = captured["request"]
    assert request.context.result_dir.name == "environment-run"
    assert request.agent_runtime.al_mcp is True
    assert request.agent_runtime.al_lsp is True
    assert request.agent_runtime.bc_mcp is True


@pytest.mark.parametrize(
    ("mutate_args", "message"),
    [
        (lambda _fixture, args: args, "does not exist"),
        (
            lambda fixture, args: ["0" * 64 if value == bugfix_lifecycle_commands.sha256_file(fixture.worker) else value for value in args],
            "hash does not match",
        ),
        (
            lambda fixture, args: [fixture.evaluator_config["password"] if value == "os-secret" else value for value in args],
            "passwords must differ",
        ),
        (
            lambda fixture, args: [fixture.evaluator_config["username"] if value == "bcb-1234567-abcdef" else value for value in args],
            "setup-owned os username",
        ),
        (
            lambda fixture, args: ["" if value == fixture.evaluator_config["password"] else value for value in args],
            "missing: password",
        ),
        (
            lambda fixture, args: [str(fixture.entry_root) if value == str(fixture.protected_root) else value for value in args],
            "disjoint",
        ),
    ],
)
def test_bugfix_lifecycle_rejects_invalid_boundary_inputs_before_collaborators(
    lifecycle_cli_fixture: LifecycleCliFixture,
    mutate_args,
    message: str,
):
    args = mutate_args(lifecycle_cli_fixture, lifecycle_cli_fixture.args("copilot"))
    lifecycle_cli_fixture.worker.unlink(missing_ok=True) if "does not exist" in message else None

    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True, return_value=None),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert message in (result.stdout + result.stderr).lower()
    load_entry.assert_not_called()
    lifecycle_factory.assert_not_called()


@pytest.mark.parametrize(
    "failure_point",
    ["entry_load", "version", "run_dir", "collaborator"],
)
def test_bugfix_lifecycle_preflight_failures_cleanup_exactly_once(
    lifecycle_cli_fixture: LifecycleCliFixture,
    failure_point: str,
):
    cleanup_calls: list[object] = []
    patches = [
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
        patch.object(
            bugfix_lifecycle_commands.LifecycleCleanup,
            "run",
            autospec=True,
            side_effect=lambda cleanup: cleanup_calls.append(cleanup.resources),
        ),
    ]
    if failure_point == "entry_load":
        patches[0] = patch.object(BugFixEntry, "load", side_effect=RuntimeError("entry load failed"))
    elif failure_point == "version":
        patches[1] = patch.object(bugfix_lifecycle_commands, "get_copilot_version", side_effect=RuntimeError("version failed"))
    elif failure_point == "run_dir":
        patches.append(patch.object(bugfix_lifecycle_commands, "prepare_run_dir", side_effect=RuntimeError("run dir failed")))
    elif failure_point == "collaborator":
        patches.append(
            patch.object(
                bugfix_lifecycle_commands.ProductionBugFixLifecycle,
                "from_request",
                side_effect=RuntimeError("collaborator failed"),
            )
        )

    with ExitStack() as stack:
        for active_patch in patches:
            stack.enter_context(active_patch)
        result = runner.invoke(app, lifecycle_cli_fixture.args("copilot"))

    assert result.exit_code == 1
    assert len(cleanup_calls) == 1
    for secret in ("os-secret", "bc-secret", "evaluator-secret"):
        assert secret not in result.stdout
        assert secret not in result.stderr


@pytest.mark.parametrize(
    ("failure_point", "message"),
    [
        ("worker", "does not exist"),
        ("worker_hash", "hash does not match"),
        ("runtime", "python_base_prefix"),
        ("credential", "passwords must differ"),
        ("container_config", "does not match"),
        ("path", "disjoint"),
    ],
)
def test_bugfix_lifecycle_validation_failures_cleanup_exactly_once_before_collaborators(
    lifecycle_cli_fixture: LifecycleCliFixture,
    failure_point: str,
    message: str,
):
    args = lifecycle_cli_fixture.args("copilot")
    if failure_point == "worker":
        lifecycle_cli_fixture.worker.unlink()
    elif failure_point == "worker_hash":
        args[args.index("--staged-worker-sha256") + 1] = "0" * 64
    elif failure_point == "runtime":
        args[args.index("--python-base-prefix") + 1] = str(lifecycle_cli_fixture.tool_root)
    elif failure_point == "credential":
        args[args.index("--agent-os-password") + 1] = lifecycle_cli_fixture.evaluator_config["password"]
    elif failure_point == "container_config":
        evaluator_config = {**lifecycle_cli_fixture.evaluator_config, "name": "unexpected-container"}
        args[args.index("--evaluator-container-config") + 1] = json.dumps(evaluator_config)
    else:
        args[args.index("--protected-root") + 1] = str(lifecycle_cli_fixture.entry_root)

    cleanup_calls: list[object] = []
    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands, "get_copilot_version") as get_version,
        patch.object(bugfix_lifecycle_commands, "prepare_run_dir") as prepare_result_dir,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(
            bugfix_lifecycle_commands.LifecycleCleanup,
            "run",
            autospec=True,
            side_effect=lambda cleanup: cleanup_calls.append(cleanup.resources),
        ),
        patch.object(bugfix_lifecycle_commands.RawSetupCleanup, "run", autospec=True) as raw_cleanup_run,
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert message in (result.stdout + result.stderr).lower()
    assert len(cleanup_calls) == 1
    load_entry.assert_not_called()
    get_version.assert_not_called()
    prepare_result_dir.assert_not_called()
    lifecycle_factory.assert_not_called()
    raw_cleanup_run.assert_not_called()


@pytest.mark.parametrize("command", ["copilot", "claude"])
@pytest.mark.parametrize("malformed_ownership", [False, True])
def test_lifecycle_output_file_is_validated_only_after_cleanup_ownership(lifecycle_cli_fixture, command, malformed_ownership):
    output_file = lifecycle_cli_fixture.protected_root.parent / "output-file"
    output_file.write_text("keep existing contents", encoding="utf-8")
    args = lifecycle_cli_fixture.args(command)
    args[args.index("--output-dir") + 1] = str(output_file)
    if malformed_ownership:
        args[args.index("--acl-paths-json") + 1] = "{"
    raw_cleanup = bugfix_lifecycle_commands.RawSetupCleanup.run
    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands, "get_copilot_version") as copilot_version,
        patch.object(bugfix_lifecycle_commands, "get_claude_version") as claude_version,
        patch.object(bugfix_lifecycle_commands, "prepare_run_dir") as prepare_result_dir,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True, return_value=None) as cleanup,
        patch.object(bugfix_lifecycle_commands.RawSetupCleanup, "run", autospec=True, side_effect=raw_cleanup) as quarantine,
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    if malformed_ownership:
        quarantine.assert_called_once()
        cleanup.assert_not_called()
        assert "valid json" in (result.stdout + result.stderr).lower()
        evidence = json.loads((lifecycle_cli_fixture.protected_root / "quarantine.json").read_text())
        assert evidence["status"] == "quarantined"
        assert evidence["reason"] == "ownership_envelope_parse_failure"
    else:
        cleanup.assert_called_once()
        quarantine.assert_not_called()
        assert "--output-dir" in result.stderr
        assert "directory" in result.stderr.lower()
    load_entry.assert_not_called()
    copilot_version.assert_not_called()
    claude_version.assert_not_called()
    prepare_result_dir.assert_not_called()
    lifecycle_factory.assert_not_called()
    assert output_file.read_text() == "keep existing contents"


def test_bugfix_lifecycle_malformed_ownership_envelope_quarantines_exactly_once_before_collaborators(
    lifecycle_cli_fixture: LifecycleCliFixture,
):
    args = lifecycle_cli_fixture.args("copilot")
    args[args.index("--acl-paths-json") + 1] = "{"
    raw_cleanup_calls: list[object] = []
    raw_cleanup_run = bugfix_lifecycle_commands.RawSetupCleanup.run

    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands, "get_copilot_version") as get_version,
        patch.object(bugfix_lifecycle_commands, "prepare_run_dir") as prepare_result_dir,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True) as cleanup_run,
        patch.object(
            bugfix_lifecycle_commands.RawSetupCleanup,
            "run",
            autospec=True,
            side_effect=lambda cleanup, error: (
                raw_cleanup_calls.append(cleanup),
                raw_cleanup_run(cleanup, error),
            )[1],
        ),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "valid json" in (result.stdout + result.stderr).lower()
    assert len(raw_cleanup_calls) == 1
    cleanup_run.assert_not_called()
    load_entry.assert_not_called()
    get_version.assert_not_called()
    prepare_result_dir.assert_not_called()
    lifecycle_factory.assert_not_called()
    quarantine = json.loads(lifecycle_cli_fixture.protected_root.joinpath("quarantine.json").read_text(encoding="utf-8"))
    assert quarantine["status"] == "quarantined"
    assert quarantine["reason"] == "ownership_envelope_parse_failure"
    assert quarantine["container_name"] == lifecycle_cli_fixture.evaluator_config["name"]
    assert quarantine["entry_root"] == str(lifecycle_cli_fixture.entry_root)
    assert quarantine["protected_root"] == str(lifecycle_cli_fixture.protected_root)
    assert quarantine["staged_worker_path"] == str(lifecycle_cli_fixture.worker)
    assert quarantine["base_python"] == str(lifecycle_cli_fixture.python)
    assert quarantine["python_base_prefix"] == str(lifecycle_cli_fixture.python_base_prefix)
    assert quarantine["cleanup_tool_roots_json"] == json.dumps([str(path) for path in lifecycle_cli_fixture.tool_roots])
    assert quarantine["owned_compiler_helper_roots"] == [str(lifecycle_cli_fixture.owned_root)]


def test_bugfix_lifecycle_handoff_prevents_duplicate_cleanup_on_lifecycle_start_failure(
    lifecycle_cli_fixture: LifecycleCliFixture,
):
    cleanup_calls: list[object] = []

    class Lifecycle:
        def run(self, request, _agent_runner, cleanup_lease):
            cleanup_lease.cleanup_as_lifecycle(lambda: cleanup_calls.append(request.provisioned_resources))
            raise RuntimeError("lifecycle start failed")

    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]),
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3"),
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request", return_value=Lifecycle()),
        patch.object(
            bugfix_lifecycle_commands.LifecycleCleanup,
            "run",
            autospec=True,
            side_effect=lambda cleanup: cleanup_calls.append(cleanup.resources),
        ),
    ):
        result = runner.invoke(app, lifecycle_cli_fixture.args("copilot"))

    assert result.exit_code == 1
    assert len(cleanup_calls) == 1


@pytest.mark.parametrize("mutation", ["absent", "missing", "tampered"])
def test_bugfix_lifecycle_rejects_invalid_acl_transaction_before_handoff_and_cleans(
    lifecycle_cli_fixture: LifecycleCliFixture,
    tmp_path: Path,
    mutation: str,
):
    args = lifecycle_cli_fixture.args("copilot")
    acl_index = args.index("--acl-paths-json") + 1
    acl_paths = list(lifecycle_cli_fixture.acl_paths)
    if mutation == "absent":
        args = _without_options(args, "--acl-paths-json")
    elif mutation == "missing":
        acl_paths.remove(lifecycle_cli_fixture.python_base_prefix)
    else:
        tampered = tmp_path / "unapproved"
        tampered.mkdir()
        acl_paths[-1] = tampered
    if mutation != "absent":
        args[acl_index] = json.dumps([str(path) for path in acl_paths])
    cleanup_calls: list[object] = []

    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(
            bugfix_lifecycle_commands.LifecycleCleanup,
            "run",
            autospec=True,
            side_effect=lambda cleanup: cleanup_calls.append(cleanup.resources),
        ),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "acl" in (result.stdout + result.stderr).lower()
    assert len(cleanup_calls) == 1
    load_entry.assert_not_called()
    lifecycle_factory.assert_not_called()


@pytest.mark.parametrize(
    ("option", "value", "message"),
    [
        ("--agent-os-username", "runner", "setup-owned os username"),
        ("--agent-os-username", "bcb-123456-abcdef", "setup-owned os username"),
        ("--agent-bc-username", "admin", "setup-owned bc username"),
        ("--agent-bc-username", "bca-1234567-abcdeg", "setup-owned bc username"),
    ],
)
def test_bugfix_lifecycle_rejects_substituted_identity_names_before_collaborators(
    lifecycle_cli_fixture: LifecycleCliFixture,
    option: str,
    value: str,
    message: str,
):
    args = lifecycle_cli_fixture.args("copilot")
    args[args.index(option) + 1] = value

    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands, "get_copilot_version") as get_version,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert message in (result.stdout + result.stderr).lower()
    load_entry.assert_not_called()
    get_version.assert_not_called()
    lifecycle_factory.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory junction regression")
@pytest.mark.parametrize("aliased_option", ["--protected-root", "--entry-root", "--staged-worker-path"])
def test_bugfix_lifecycle_rejects_root_and_worker_junction_aliases_before_collaborators(
    lifecycle_cli_fixture: LifecycleCliFixture,
    tmp_path: Path,
    aliased_option: str,
):
    args = lifecycle_cli_fixture.args("copilot")
    if aliased_option == "--staged-worker-path":
        target = lifecycle_cli_fixture.worker.parent
        aliased_path = tmp_path / "worker-alias" / lifecycle_cli_fixture.worker.name
    else:
        target = lifecycle_cli_fixture.protected_root if aliased_option == "--protected-root" else lifecycle_cli_fixture.entry_root
        aliased_path = tmp_path / f"{aliased_option.removeprefix('--')}-alias"
    _create_junction(aliased_path.parent if aliased_option == "--staged-worker-path" else aliased_path, target)
    args[args.index(aliased_option) + 1] = str(aliased_path)

    with (
        patch.object(BugFixEntry, "load", return_value=[lifecycle_cli_fixture.entry]) as load_entry,
        patch.object(bugfix_lifecycle_commands, "get_copilot_version", return_value="1.2.3") as get_version,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True, return_value=None),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "reparse" in (result.stdout + result.stderr).lower()
    load_entry.assert_not_called()
    get_version.assert_not_called()
    lifecycle_factory.assert_not_called()


@pytest.mark.parametrize("root_option", ["--entry-root", "--protected-root"])
def test_bugfix_lifecycle_rejects_non_directory_roots_before_collaborators(
    lifecycle_cli_fixture: LifecycleCliFixture,
    tmp_path: Path,
    root_option: str,
):
    invalid_root = tmp_path / f"{root_option.removeprefix('--')}.txt"
    invalid_root.write_text("not a directory", encoding="utf-8")
    args = lifecycle_cli_fixture.args("copilot")
    args[args.index(root_option) + 1] = str(invalid_root)

    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True, return_value=None),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "must be an existing" in (result.stdout + result.stderr).lower()
    load_entry.assert_not_called()
    lifecycle_factory.assert_not_called()


def test_bugfix_lifecycle_rejects_missing_replay_file_before_collaborators(lifecycle_cli_fixture: LifecycleCliFixture):
    args = lifecycle_cli_fixture.args("copilot", replay=True)
    lifecycle_cli_fixture.replay_patch.unlink()

    with (
        patch.object(BugFixEntry, "load") as load_entry,
        patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory,
        patch.object(bugfix_lifecycle_commands.LifecycleCleanup, "run", autospec=True, return_value=None),
    ):
        result = runner.invoke(app, args)

    assert result.exit_code == 2
    assert "--replay-patch" in (result.stdout + result.stderr).lower()
    load_entry.assert_not_called()
    lifecycle_factory.assert_not_called()


def test_bugfix_lifecycle_category_cannot_be_varied(lifecycle_cli_fixture: LifecycleCliFixture):
    with patch.object(bugfix_lifecycle_commands.ProductionBugFixLifecycle, "from_request") as lifecycle_factory:
        result = runner.invoke(
            app,
            [*lifecycle_cli_fixture.args("copilot"), "--category", "test-generation"],
        )

    assert result.exit_code == 2
    assert "no such option" in (result.stdout + result.stderr).lower()
    lifecycle_factory.assert_not_called()


@pytest.mark.integration
def test_result_summarize_creates_all_outputs(sample_results_directory, problem_statement_dir):
    base_path, run_id, dataset_path = sample_results_directory
    results_dir = base_path / run_id
    for result_path in results_dir.glob("*.jsonl"):
        payload = json.loads(result_path.read_text())
        payload["agent_version"] = "1.2.3"
        result_path.write_text(json.dumps(payload), encoding="utf-8")

    with (
        patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_statement_dir)),
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=dataset_path),
        patch.object(evaluate_commands, "get_copilot_version", side_effect=AssertionError("Must use artifact version")),
        patch.object(evaluate_commands, "get_claude_version", side_effect=AssertionError("Must use artifact version")),
        patch.object(evaluate_commands, "get_pr_review_version", side_effect=AssertionError("Must use artifact version")),
    ):
        result = runner.invoke(
            app,
            [
                "result",
                "summarize",
                "--category",
                "bug-fix",
                "--run-id",
                run_id,
                "--result-dir",
                str(base_path),
            ],
        )

    assert result.exit_code == 0, f"Command failed:\nstdout: {result.stdout}\nstderr: {result.stderr}\nexception: {result.exception}"
    assert (results_dir / "bceval_results.jsonl").exists()
    assert (results_dir / "evaluation_summary.json").exists()

    summary = json.loads((results_dir / "evaluation_summary.json").read_text())
    assert summary["total"] == 3
    assert summary["resolved"] == 2
    assert summary["failed"] == 1
    assert summary["build"] == 3
    assert summary["agent_version"] == "1.2.3"
    exported = (results_dir / "bceval_results.jsonl").read_text().splitlines()
    assert all(json.loads(line)["metadata"]["agent_version"] == "1.2.3" for line in exported)


@pytest.mark.integration
def test_result_summarize_verifies_summary_calculations(sample_results_directory, problem_statement_dir):
    base_path, run_id, dataset_path = sample_results_directory
    results_dir = base_path / run_id

    with (
        patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_statement_dir)),
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=dataset_path),
    ):
        result = runner.invoke(
            app,
            [
                "result",
                "summarize",
                "--category",
                "bug-fix",
                "--run-id",
                run_id,
                "--result-dir",
                str(base_path),
            ],
        )

    assert result.exit_code == 0

    summary = json.loads((results_dir / "evaluation_summary.json").read_text())

    # Verify averages (120 + 80 + 95) / 3 = 98.33...
    assert "average_duration" in summary
    assert summary["average_duration"] > 98.0
    assert summary["average_duration"] < 99.0

    # Verify token averages
    assert "average_prompt_tokens" in summary
    assert "average_completion_tokens" in summary


@pytest.mark.integration
def test_result_summarize_missing_directory_fails_gracefully(tmp_path):
    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--category",
            "bug-fix",
            "--run-id",
            "nonexistent_run",
            "--result-dir",
            str(tmp_path),
        ],
    )

    # Command should exit with error code 1 when directory doesn't exist
    assert result.exit_code == 1


@pytest.mark.integration
def test_result_summarize_no_matching_files_fails_gracefully(tmp_path):
    run_id = "empty_run"
    results_dir = tmp_path / run_id
    results_dir.mkdir(parents=True)

    # Create a file that doesn't match the expected pattern
    (results_dir / "random_file.txt").write_text("not a result")

    result = runner.invoke(
        app,
        [
            "result",
            "summarize",
            "--category",
            "bug-fix",
            "--run-id",
            run_id,
            "--result-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1


@pytest.mark.integration
def test_result_summarize_with_custom_pattern(sample_results_directory, problem_statement_dir):
    base_path, run_id, dataset_path = sample_results_directory

    with (
        patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_statement_dir)),
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=dataset_path),
    ):
        result = runner.invoke(
            app,
            [
                "result",
                "summarize",
                "--category",
                "bug-fix",
                "--run-id",
                run_id,
                "--result-dir",
                str(base_path),
                "--result-pattern",
                "*.jsonl",
            ],
        )

    assert result.exit_code == 0


@pytest.mark.integration
def test_dataset_list_displays_all_entries(sample_dataset_file_for_cli):
    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=sample_dataset_file_for_cli):
        result = runner.invoke(
            app,
            [
                "dataset",
                "list",
            ],
        )

    assert result.exit_code == 0
    assert "microsoftInternal__NAV-1" in result.stdout
    assert "microsoftInternal__NAV-2" in result.stdout
    assert "microsoftInternal__NAV-3" in result.stdout
    assert "Found 3 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_bc_version_returns_entry_version(sample_dataset_file_for_cli):
    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=sample_dataset_file_for_cli):
        result = runner.invoke(
            app,
            [
                "dataset",
                "version",
                "microsoftInternal__NAV-2",
                "--category",
                "bug-fix",
            ],
        )

    assert result.exit_code == 0, f"Command failed: {result.stdout}\n{result.exception}"
    assert "27.0" in result.stdout
    assert "26.5" not in result.stdout


@pytest.mark.integration
def test_dataset_list_missing_file_fails_gracefully(tmp_path):
    nonexistent_path = tmp_path / "nonexistent.jsonl"

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=nonexistent_path):
        result = runner.invoke(
            app,
            [
                "dataset",
                "list",
            ],
        )

    assert result.exit_code != 0


@pytest.mark.integration
def test_dataset_list_empty_file_shows_zero_entries(tmp_path):
    empty_dataset = tmp_path / "empty.jsonl"
    empty_dataset.write_text("")

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=empty_dataset):
        result = runner.invoke(
            app,
            [
                "dataset",
                "list",
            ],
        )

    assert result.exit_code == 0
    assert "Found 0 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_list_single_entry(tmp_path):
    entry = create_dataset_entry(instance_id="microsoftInternal__NAV-100")
    dataset_path = create_dataset_file(tmp_path, [entry])

    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=dataset_path):
        result = runner.invoke(
            app,
            [
                "dataset",
                "list",
            ],
        )

    assert result.exit_code == 0
    assert "microsoftInternal__NAV-100" in result.stdout
    assert "Found 1 entry(ies)" in result.stdout


@pytest.mark.integration
def test_dataset_list_verifies_entry_format(sample_dataset_file_for_cli):
    with patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=sample_dataset_file_for_cli):
        result = runner.invoke(
            app,
            [
                "dataset",
                "list",
            ],
        )

    assert result.exit_code == 0
    # Should contain instance_id of first entry
    assert "microsoftInternal__NAV-1" in result.stdout


@pytest.fixture
def sample_leaderboard_and_summary(tmp_path):
    leaderboard_dir = tmp_path / "_data"
    leaderboard_dir.mkdir()
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"
    testgen_leaderboard_path = leaderboard_dir / "test-generation.json"
    summary_path = tmp_path / "summary.json"

    # Create bug-fix leaderboard with 2 runs from different agents
    # Generate instance_results for pass^k calculation
    copilot_instance_results = {f"test__inst_{i}": (i < 6) for i in range(10)}  # 6 resolved
    mini_instance_results = {f"test__inst_{i}": (i < 7) for i in range(10)}  # 7 resolved

    bugfix_data = {
        "runs": [
            {
                "total": 10,
                "resolved": 6,
                "failed": 4,
                "build": 9,
                "percentage": 60.0,
                "instance_results": copilot_instance_results,
                "date": "2025-01-10",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "copilot",
                "average_duration": 120.5,
                "average_prompt_tokens": 5000.0,
                "average_completion_tokens": 1500.0,
                "average_llm_duration": 80.0,
                "github_run_id": "run_001",
                "experiment": {
                    "mcp_servers": ["server1", "server2"],
                    "custom_instructions": True,
                    "custom_agent": None,
                },
                "benchmark_version": "0.1.0",
            },
            {
                "total": 10,
                "resolved": 7,
                "failed": 3,
                "build": 10,
                "percentage": 70.0,
                "instance_results": mini_instance_results,
                "date": "2025-01-12",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "mini",
                "average_duration": 95.0,
                "average_prompt_tokens": 3500.0,
                "average_completion_tokens": 1000.0,
                "average_llm_duration": 65.0,
                "github_run_id": "run_003",
                "experiment": {
                    "mcp_servers": None,
                    "custom_instructions": False,
                    "custom_agent": None,
                },
                "benchmark_version": "0.1.0",
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4o",
                "agent_name": "copilot",
                "category": "bug-fix",
                "experiment": {
                    "mcp_servers": ["server1", "server2"],
                    "custom_instructions": True,
                    "custom_agent": None,
                },
                "total": 10,
                "num_runs": 1,
                "average_duration": 120.5,
                "average": 0.6,
                "ci_low": None,
                "ci_high": None,
                "pass_hat_5": None,
                "benchmark_version": "0.1.0",
            },
            {
                "model": "gpt-4o",
                "agent_name": "mini",
                "category": "bug-fix",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 95.0,
                "average": 0.7,
                "ci_low": None,
                "ci_high": None,
                "pass_hat_5": None,
                "benchmark_version": "0.1.0",
            },
        ],
    }

    # Create test-generation leaderboard with 1 entry
    testgen_instance_results = {f"test__inst_{i}": (i < 5) for i in range(10)}  # 5 resolved

    testgen_data = {
        "runs": [
            {
                "total": 10,
                "resolved": 5,
                "failed": 5,
                "build": 8,
                "percentage": 50.0,
                "instance_results": testgen_instance_results,
                "date": "2025-01-11",
                "model": "gpt-4-turbo",
                "category": "test-generation",
                "agent_name": "copilot",
                "average_duration": 110.0,
                "average_prompt_tokens": 4500.0,
                "average_completion_tokens": 1200.0,
                "average_llm_duration": 75.0,
                "github_run_id": "run_002",
                "experiment": {
                    "mcp_servers": None,
                    "custom_instructions": False,
                    "custom_agent": None,
                },
                "benchmark_version": "0.1.0",
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4-turbo",
                "agent_name": "copilot",
                "category": "test-generation",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 110.0,
                "average": 0.5,
                "ci_low": None,
                "ci_high": None,
                "pass_hat_5": None,
                "benchmark_version": "0.1.0",
            },
        ],
    }

    with bugfix_leaderboard_path.open("w") as f:
        json.dump(bugfix_data, f, indent=2)

    with testgen_leaderboard_path.open("w") as f:
        json.dump(testgen_data, f, indent=2)

    # Create a new summary to update (updated copilot + gpt-4o + server1, server2)
    new_summary_instance_results = {f"test__inst_{i}": (i < 8) for i in range(10)}  # 8 resolved

    new_summary = {
        "total": 10,
        "resolved": 8,
        "failed": 2,
        "build": 10,
        "percentage": 80.0,
        "instance_results": new_summary_instance_results,
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 130.0,
        "average_prompt_tokens": 5200.0,
        "average_completion_tokens": 1600.0,
        "average_llm_duration": 90.0,
        "github_run_id": "run_004",
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
        "benchmark_version": "0.1.0",
    }

    with summary_path.open("w") as f:
        json.dump(new_summary, f, indent=2)

    return leaderboard_dir, summary_path


@pytest.mark.integration
def test_result_update_replaces_existing_entry(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
            "--n",
            "1",
        ],
    )

    assert result.exit_code == 0, f"Command failed:\nstdout: {result.stdout}\nstderr: {result.stderr}\nexception: {result.exception}"

    # Verify bug-fix leaderboard still has 2 aggregates (not 3)
    with bugfix_leaderboard_path.open() as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard["aggregate"]) == 2, "Should still have 2 aggregates (replaced, not added)"

    # Find the updated entry and verify it matches
    updated_agg = None
    for agg in updated_leaderboard["aggregate"]:
        exp = agg.get("experiment") or {}
        if agg["agent_name"] == "copilot" and agg["model"] == "gpt-4o" and exp.get("mcp_servers") == ["server1", "server2"] and exp.get("custom_instructions") is True:
            updated_agg = agg
            break

    assert updated_agg is not None, "Should find the updated copilot + gpt-4o + server1, server2 aggregate"
    # Find the corresponding run
    latest_run = next(r for r in updated_leaderboard["runs"] if r["github_run_id"] == "run_004")
    assert latest_run["resolved"] == 8, "Should have updated resolved count"
    assert latest_run["build"] == 10, "Should have updated build count"
    assert latest_run["average_prompt_tokens"] == 5200.0, "Should have updated average_prompt_tokens"


@pytest.mark.integration
def test_result_update_adds_new_entry(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    summary_path = leaderboard_dir.parent / "new_agent_summary.json"

    # Create a new summary for a different agent
    new_agent_instance_results = {f"test__inst_{i}": (i < 9) for i in range(10)}  # 9 resolved

    new_summary = {
        "total": 10,
        "resolved": 9,
        "failed": 1,
        "build": 10,
        "percentage": 90.0,
        "instance_results": new_agent_instance_results,
        "date": "2025-01-16",
        "model": "gpt-4o",
        "category": "test-generation",
        "agent_name": "new-agent",
        "average_duration": 100.0,
        "average_prompt_tokens": 4800.0,
        "average_completion_tokens": 1400.0,
        "average_llm_duration": 70.0,
        "github_run_id": "run_005",
        "experiment": {
            "mcp_servers": None,
            "custom_instructions": False,
            "custom_agent": None,
        },
        "benchmark_version": "0.1.0",
    }

    with summary_path.open("w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
            "--n",
            "1",
        ],
    )

    assert result.exit_code == 0

    # Verify leaderboard now has 2 aggregates in test-generation
    with (leaderboard_dir / "test-generation.json").open() as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard["aggregate"]) == 2, "Should now have 2 aggregates (added new in test-generation)"

    # Find the new entry
    new_agg = None
    for agg in updated_leaderboard["aggregate"]:
        if agg["agent_name"] == "new-agent" and agg["model"] == "gpt-4o":
            new_agg = agg
            break

    assert new_agg is not None, "Should find the new aggregate for new-agent"
    new_run = next(r for r in updated_leaderboard["runs"] if r["agent_name"] == "new-agent")
    assert new_run["resolved"] == 9, "Should have correct resolved count"


@pytest.mark.integration
def test_result_update_distinguishes_by_mcp_servers(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    summary_path = leaderboard_dir.parent / "copilot_different_mcp_summary.json"

    # Create a new summary for copilot + gpt-4o but WITHOUT mcp_servers (different from existing)
    diff_mcp_instance_results = {f"test__inst_{i}": (i < 7) for i in range(10)}  # 7 resolved

    new_summary = {
        "total": 10,
        "resolved": 7,
        "failed": 3,
        "build": 9,
        "percentage": 70.0,
        "instance_results": diff_mcp_instance_results,
        "date": "2025-01-17",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 115.0,
        "average_prompt_tokens": 4900.0,
        "average_completion_tokens": 1350.0,
        "average_llm_duration": 78.0,
        "github_run_id": "run_006",
        "experiment": {
            "mcp_servers": None,  # Different from existing ["server1", "server2"]
            "custom_instructions": False,  # Different from existing True
            "custom_agent": None,
        },
        "benchmark_version": "0.1.0",
    }

    with summary_path.open("w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
            "--n",
            "1",
        ],
    )

    assert result.exit_code == 0

    # Verify bug-fix leaderboard now has 3 aggregates (not replaced because mcp_servers differ)
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"
    with bugfix_leaderboard_path.open() as f:
        updated_leaderboard = json.load(f)

    assert len(updated_leaderboard["aggregate"]) == 3, "Should have 3 aggregates in bug-fix (added new because mcp_servers differ)"

    # Verify both copilot + gpt-4o aggregates exist
    copilot_gpt4o_aggs = [a for a in updated_leaderboard["aggregate"] if a["agent_name"] == "copilot" and a["model"] == "gpt-4o"]

    assert len(copilot_gpt4o_aggs) == 2, "Should have 2 different copilot + gpt-4o aggregates"

    # Find each by experiment.mcp_servers
    with_servers = next((a for a in copilot_gpt4o_aggs if (a.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]), None)
    without_servers = next((a for a in copilot_gpt4o_aggs if (a.get("experiment") or {}).get("mcp_servers") is None), None)

    assert with_servers is not None
    assert without_servers is not None
    assert with_servers["average"] == 0.6, "Original aggregate should be unchanged"
    assert without_servers["average"] == 0.7, "New aggregate should have new values"


@pytest.mark.integration
def test_result_update_ensures_newline_at_end_of_file(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary

    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )

    assert result.exit_code == 0

    # Verify file ends with newline
    with (leaderboard_dir / "bug-fix.json").open("rb") as f:
        content = f.read()
        assert content.endswith(b"\n"), "Leaderboard file should end with a newline character"


@pytest.mark.integration
def test_result_update_does_not_add_multiple_newlines_when_run_twice(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary

    # Run update command first time
    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )
    assert result.exit_code == 0

    # Read file after first update
    with (leaderboard_dir / "bug-fix.json").open("rb") as f:
        content_after_first = f.read()

    # Count trailing newlines after first update
    trailing_newlines_first = len(content_after_first) - len(content_after_first.rstrip(b"\n"))
    assert trailing_newlines_first == 1, "File should have exactly 1 trailing newline after first update"

    # Run update command second time with same summary
    result = runner.invoke(
        app,
        [
            "result",
            "update",
            str(summary_path),
            "--leaderboard-dir",
            str(leaderboard_dir),
        ],
    )
    assert result.exit_code == 0

    # Read file after second update
    with (leaderboard_dir / "bug-fix.json").open("rb") as f:
        content_after_second = f.read()

    # Count trailing newlines after second update
    trailing_newlines_second = len(content_after_second) - len(content_after_second.rstrip(b"\n"))
    assert trailing_newlines_second == 1, "File should still have exactly 1 trailing newline after second update, not 2"


@pytest.mark.integration
def test_result_update_stores_multiple_results_with_default_n(sample_leaderboard_and_summary):
    leaderboard_dir, summary_path = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    # Default n=5 - should add as new entry (even though combination exists)
    # because n>1 means we keep multiple results
    multi_results_instance = {f"test__inst_{i}": (i < 8) for i in range(10)}  # 8 resolved

    new_summary = {
        "total": 10,
        "resolved": 8,
        "failed": 2,
        "build": 10,
        "percentage": 80.0,
        "instance_results": multi_results_instance,
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 130.0,
        "average_prompt_tokens": 5200.0,
        "average_completion_tokens": 1600.0,
        "average_llm_duration": 90.0,
        "github_run_id": "run_new_1",
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
        "benchmark_version": "0.1.0",
    }

    with summary_path.open("w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir)],
    )

    assert result.exit_code == 0

    with bugfix_leaderboard_path.open() as f:
        updated_leaderboard = json.load(f)

    # Should still have 2 aggregates (the new result is added to an existing combination's runs)
    assert len(updated_leaderboard["aggregate"]) == 2

    # Verify we have 2 runs for copilot + gpt-4o + server1,server2 (original + new)
    copilot_runs = [r for r in updated_leaderboard["runs"] if r["agent_name"] == "copilot" and r["model"] == "gpt-4o" and (r.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]]
    assert len(copilot_runs) == 2  # Original + new run


@pytest.mark.integration
def test_result_update_replaces_oldest_when_exceeding_n(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    # First, add 4 more results to have 5 total for copilot + gpt-4o + servers combination (default n=5)
    oldest_instance_results = {f"test__inst_{i}": (i < 7) for i in range(10)}  # 7 resolved

    base_summary = {
        "total": 10,
        "resolved": 7,
        "failed": 3,
        "build": 9,
        "percentage": 70.0,
        "instance_results": oldest_instance_results,
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 120.0,
        "average_prompt_tokens": 5000.0,
        "average_completion_tokens": 1500.0,
        "average_llm_duration": 85.0,
        "experiment": {
            "mcp_servers": ["server1", "server2"],
            "custom_instructions": True,
            "custom_agent": None,
        },
        "benchmark_version": "0.1.0",
    }

    summary_path = leaderboard_dir.parent / "test_summary.json"

    # Add results to fill up to n=5 (original is from 2025-01-10)
    for _, (day, run_id) in enumerate([("2025-01-16", "run_second"), ("2025-01-17", "run_third"), ("2025-01-18", "run_fourth"), ("2025-01-19", "run_fifth")]):
        summary = {**base_summary, "date": day, "github_run_id": run_id}
        with summary_path.open("w") as f:
            json.dump(summary, f, indent=2)
        runner.invoke(app, ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir)])

    # Now we should have 5 runs for this combination
    with bugfix_leaderboard_path.open() as f:
        leaderboard = json.load(f)

    copilot_runs = [r for r in leaderboard["runs"] if r["agent_name"] == "copilot" and r["model"] == "gpt-4o" and (r.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]]
    assert len(copilot_runs) == 5

    # Now add a 6th result - should replace oldest (2025-01-10)
    newest_instance_results = {f"test__inst_{i}": (i < 9) for i in range(10)}  # 9 resolved
    summary_new = {
        **base_summary,
        "date": "2025-01-20",
        "github_run_id": "run_sixth",
        "resolved": 9,
        "failed": 1,
        "build": 10,
        "percentage": 90.0,
        "instance_results": newest_instance_results,
    }
    with summary_path.open("w") as f:
        json.dump(summary_new, f, indent=2)

    result = runner.invoke(app, ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir)])
    assert result.exit_code == 0

    with bugfix_leaderboard_path.open() as f:
        final_leaderboard = json.load(f)

    # Should still have 5 runs for this combination
    final_copilot_runs = [r for r in final_leaderboard["runs"] if r["agent_name"] == "copilot" and r["model"] == "gpt-4o" and (r.get("experiment") or {}).get("mcp_servers") == ["server1", "server2"]]
    assert len(final_copilot_runs) == 5

    # The oldest (2025-01-10) should be gone, replaced by 2025-01-20
    dates = sorted(r["date"] for r in final_copilot_runs)
    assert dates == ["2025-01-16", "2025-01-17", "2025-01-18", "2025-01-19", "2025-01-20"]

    # Verify the newest entry has the correct resolved count
    newest = next(r for r in final_copilot_runs if r["date"] == "2025-01-20")
    assert newest["resolved"] == 9
    assert newest["github_run_id"] == "run_sixth"


@pytest.mark.integration
def test_result_refresh_recalculates_aggregates(sample_leaderboard_and_summary):
    leaderboard_dir, _ = sample_leaderboard_and_summary
    bugfix_leaderboard_path = leaderboard_dir / "bug-fix.json"

    # Corrupt the aggregates to verify refresh recalculates them
    with bugfix_leaderboard_path.open() as f:
        leaderboard = json.load(f)

    for agg in leaderboard["aggregate"]:
        agg["average"] = 999.0  # Invalid value

    with bugfix_leaderboard_path.open("w") as f:
        json.dump(leaderboard, f, indent=2)

    # Run refresh command
    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(leaderboard_dir)])
    assert result.exit_code == 0

    # Verify aggregates were recalculated correctly
    with bugfix_leaderboard_path.open() as f:
        refreshed = json.load(f)

    # Should have 2 aggregates (copilot with servers, mini without)
    assert len(refreshed["aggregate"]) == 2

    # All average values should be recalculated (not 999)
    for agg in refreshed["aggregate"]:
        assert agg["average"] != 999.0
        assert agg["average"] > 0


@pytest.mark.integration
def test_result_refresh_handles_empty_leaderboard(tmp_path):
    # Create an empty leaderboard file
    empty_leaderboard = tmp_path / "bug-fix.json"
    empty_leaderboard.write_text("[]")

    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


@pytest.mark.integration
def test_result_refresh_handles_legacy_runs_without_instance_results(tmp_path):
    """Test that refresh handles runs without instance_results."""
    leaderboard_path = tmp_path / "bug-fix.json"

    legacy_data = {
        "runs": [
            {
                "total": 10,
                "date": "2025-01-10",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "legacy-agent",
                "average_duration": 100.0,
                "average_prompt_tokens": 4000.0,
                "average_completion_tokens": 1200.0,
                "average_llm_duration": 70.0,
                "github_run_id": "run_legacy",
                "experiment": None,
                "benchmark_version": "0.1.0",
                "resolved": 6,
                "failed": 4,
                "build": 9,
                "percentage": 60.0,
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4o",
                "agent_name": "legacy-agent",
                "category": "bug-fix",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 100.0,
                "average": 0.0,  # Incorrectly set to 0
                "ci_low": None,
                "ci_high": None,
                "benchmark_version": "0.1.0",
            },
        ],
    }

    with leaderboard_path.open("w") as f:
        json.dump(legacy_data, f, indent=2)

    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(tmp_path)])
    assert result.exit_code == 0

    with leaderboard_path.open() as f:
        refreshed = json.load(f)

    # Should fall back to pass rate (resolved/total) from run
    assert refreshed["aggregate"][0]["average"] == 0.6


@pytest.mark.integration
def test_result_refresh_distinguishes_unscored_and_zero_averages(tmp_path):
    leaderboard_path = tmp_path / "bug-fix.json"
    common = {
        "total": 1,
        "date": "2025-01-10",
        "model": "gpt-4o",
        "category": "bug-fix",
        "average_duration": 100.0,
        "average_prompt_tokens": 4000.0,
        "average_completion_tokens": 1200.0,
        "average_llm_duration": 70.0,
        "experiment": None,
        "benchmark_version": "0.1.0",
        "resolved": 0,
        "build": 0,
    }
    data = {
        "runs": [
            {
                **common,
                "agent_name": "infrastructure-only",
                "failed": 0,
                "infrastructure_failed": 1,
                "percentage": None,
                "instance_results": {},
                "github_run_id": "run_infrastructure",
            },
            {
                **common,
                "agent_name": "evaluated-failure",
                "failed": 1,
                "infrastructure_failed": 0,
                "percentage": 0.0,
                "instance_results": {"test__1": False},
                "github_run_id": "run_evaluated",
            },
        ],
        "aggregate": [],
    }
    with leaderboard_path.open("w") as f:
        json.dump(data, f, indent=2)

    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(tmp_path)])

    assert result.exit_code == 0
    with leaderboard_path.open() as f:
        refreshed = json.load(f)
    averages = {aggregate["agent_name"]: aggregate["average"] for aggregate in refreshed["aggregate"]}
    assert averages == {
        "infrastructure-only": None,
        "evaluated-failure": 0.0,
    }


@pytest.mark.integration
def test_result_refresh_separates_runs_by_benchmark_version(tmp_path):
    """Test that runs with different benchmark versions produce separate aggregates."""
    leaderboard_path = tmp_path / "bug-fix.json"

    # Create runs with same agent/model but different benchmark versions
    data = {
        "runs": [
            {
                "total": 10,
                "resolved": 6,
                "failed": 4,
                "build": 10,
                "percentage": 60.0,
                "instance_results": {f"test__inst_{i}": (i < 6) for i in range(10)},
                "date": "2025-01-10",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "copilot",
                "average_duration": 100.0,
                "average_prompt_tokens": 4000.0,
                "average_completion_tokens": 1200.0,
                "average_llm_duration": 70.0,
                "github_run_id": "run_v1",
                "experiment": None,
                "benchmark_version": "0.1.0",
            },
            {
                "total": 10,
                "resolved": 8,
                "failed": 2,
                "build": 10,
                "percentage": 80.0,
                "instance_results": {f"test__inst_{i}": (i < 8) for i in range(10)},
                "date": "2025-01-15",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "copilot",
                "average_duration": 95.0,
                "average_prompt_tokens": 4200.0,
                "average_completion_tokens": 1300.0,
                "average_llm_duration": 65.0,
                "github_run_id": "run_v2",
                "experiment": None,
                "benchmark_version": "0.2.0",
            },
        ],
        "aggregate": [],
    }

    with leaderboard_path.open("w") as f:
        json.dump(data, f, indent=2)

    result = runner.invoke(app, ["result", "refresh", "--leaderboard-dir", str(tmp_path)])
    assert result.exit_code == 0

    with leaderboard_path.open() as f:
        refreshed = json.load(f)

    # Should have 2 separate aggregates (one per version)
    assert len(refreshed["aggregate"]) == 2

    versions = {agg["benchmark_version"] for agg in refreshed["aggregate"]}
    assert versions == {"0.1.0", "0.2.0"}

    # Verify correct averages per version
    v1_agg = next(a for a in refreshed["aggregate"] if a["benchmark_version"] == "0.1.0")
    v2_agg = next(a for a in refreshed["aggregate"] if a["benchmark_version"] == "0.2.0")
    assert v1_agg["average"] == 0.6
    assert v2_agg["average"] == 0.8


@pytest.mark.integration
def test_result_update_groups_by_benchmark_version(tmp_path):
    """Test that result update respects benchmark_version in combination key."""
    leaderboard_dir = tmp_path / "leaderboard"
    leaderboard_dir.mkdir()
    leaderboard_path = leaderboard_dir / "bug-fix.json"

    # Initial data with v0.1.0
    initial_data = {
        "runs": [
            {
                "total": 10,
                "resolved": 5,
                "failed": 5,
                "build": 10,
                "percentage": 50.0,
                "instance_results": {f"test__inst_{i}": (i < 5) for i in range(10)},
                "date": "2025-01-10",
                "model": "gpt-4o",
                "category": "bug-fix",
                "agent_name": "copilot",
                "average_duration": 100.0,
                "average_prompt_tokens": 4000.0,
                "average_completion_tokens": 1200.0,
                "average_llm_duration": 70.0,
                "github_run_id": "run_v1",
                "experiment": None,
                "benchmark_version": "0.1.0",
            },
        ],
        "aggregate": [
            {
                "model": "gpt-4o",
                "agent_name": "copilot",
                "category": "bug-fix",
                "experiment": None,
                "total": 10,
                "num_runs": 1,
                "average_duration": 100.0,
                "average": 0.5,
                "ci_low": None,
                "ci_high": None,
                "pass_hat_5": None,
                "benchmark_version": "0.1.0",
            },
        ],
    }

    with leaderboard_path.open("w") as f:
        json.dump(initial_data, f, indent=2)

    # Add a new run with v0.2.0 (same agent/model, different version)
    summary_path = tmp_path / "new_summary.json"
    new_summary = {
        "total": 10,
        "resolved": 7,
        "failed": 3,
        "build": 10,
        "percentage": 70.0,
        "instance_results": {f"test__inst_{i}": (i < 7) for i in range(10)},
        "date": "2025-01-15",
        "model": "gpt-4o",
        "category": "bug-fix",
        "agent_name": "copilot",
        "average_duration": 95.0,
        "average_prompt_tokens": 4200.0,
        "average_completion_tokens": 1300.0,
        "average_llm_duration": 65.0,
        "github_run_id": "run_v2",
        "experiment": None,
        "benchmark_version": "0.2.0",
    }

    with summary_path.open("w") as f:
        json.dump(new_summary, f, indent=2)

    result = runner.invoke(
        app,
        ["result", "update", str(summary_path), "--leaderboard-dir", str(leaderboard_dir), "--n", "5"],
    )
    assert result.exit_code == 0

    with leaderboard_path.open() as f:
        updated = json.load(f)

    # Should have 2 runs and 2 aggregates (not merged)
    assert len(updated["runs"]) == 2
    assert len(updated["aggregate"]) == 2

    # Verify both versions exist separately
    run_versions = {r["benchmark_version"] for r in updated["runs"]}
    agg_versions = {a["benchmark_version"] for a in updated["aggregate"]}
    assert run_versions == {"0.1.0", "0.2.0"}
    assert agg_versions == {"0.1.0", "0.2.0"}
