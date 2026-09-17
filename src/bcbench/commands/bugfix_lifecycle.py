from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, cast

import typer

from bcbench.agent import get_claude_version, get_copilot_version, run_claude_code, run_copilot_agent
from bcbench.agent.shared.contained_process import AgentExecutionPolicy, WindowsIdentity
from bcbench.agent.shared.env import production_agent_profile_environment
from bcbench.cli_options import (
    ClaudeCodeModel,
    ContainerCompany,
    ContainerMcpUrl,
    ContainerName,
    ContainerPassword,
    ContainerServerInstance,
    ContainerServerUrl,
    ContainerUsername,
    CopilotModel,
    LifecycleAclPathsJson,
    LifecycleAgentBcPassword,
    LifecycleAgentBcUsername,
    LifecycleAgentContainerConfig,
    LifecycleAgentOsPassword,
    LifecycleAgentOsSid,
    LifecycleAgentOsUsername,
    LifecycleAlLsp,
    LifecycleAlMcp,
    LifecycleBasePython,
    LifecycleBcMcp,
    LifecycleCleanupToolRootsJson,
    LifecycleEntryRoot,
    LifecycleEvaluatorContainerConfig,
    LifecycleExpectedContainerId,
    LifecycleExpectedInvocationId,
    LifecycleOwnedCompilerHelperRoots,
    LifecycleProtectedRoot,
    LifecyclePythonBasePrefix,
    LifecycleReplayPatch,
    LifecycleStagedWorkerPath,
    LifecycleStagedWorkerSha256,
    OutputDir,
    RunId,
)
from bcbench.config import get_config
from bcbench.dataset import BugFixEntry
from bcbench.evaluate.bugfix_lifecycle import (
    BugFixLifecyclePaths,
    BugFixLifecycleRequest,
    CleanupLease,
    LifecycleCleanup,
    OwnedLifecycleRoot,
    ProductionBugFixLifecycle,
    ProvisionedLifecycleResources,
    RawSetupCleanup,
    sha256_file,
)
from bcbench.evaluate.bugfix_lifecycle.path_safety import (
    absolute_path,
    reject_reparse_components,
    require_disjoint,
    require_strict_descendant,
    validate_lifecycle_paths,
    validate_provisioned_lifecycle_resources,
)
from bcbench.operations import prepare_run_dir
from bcbench.types import AgentHarness, AgentMetrics, AgentRuntimeConfig, ContainerConfig, EvaluationCategory, EvaluationContext, ExperimentConfiguration

_config = get_config()
_CATEGORY = EvaluationCategory.BUG_FIX
LifecycleAgentInvoker = Callable[
    [EvaluationContext[BugFixEntry], AgentExecutionPolicy, AgentRuntimeConfig, Path],
    tuple[AgentMetrics | None, ExperimentConfiguration | None],
]
_SETUP_OS_USERNAME = re.compile(r"bcb-[a-f0-9]{7}-[a-f0-9]{6}", re.IGNORECASE)
_SETUP_BC_USERNAME = re.compile(r"bca-[a-f0-9]{7}-[a-f0-9]{6}", re.IGNORECASE)

bugfix_lifecycle_app = typer.Typer(
    help="Run the production bug-fix lifecycle with isolated agent and evaluator identities",
    no_args_is_help=True,
)


@bugfix_lifecycle_app.command("copilot")
def bugfix_lifecycle_copilot(
    entry_id: Annotated[str, typer.Argument(help="Bug-fix entry ID to evaluate")],
    entry_root: LifecycleEntryRoot,
    protected_root: LifecycleProtectedRoot,
    agent_os_username: LifecycleAgentOsUsername,
    agent_os_password: LifecycleAgentOsPassword,
    agent_bc_username: LifecycleAgentBcUsername,
    agent_bc_password: LifecycleAgentBcPassword,
    expected_container_id: LifecycleExpectedContainerId,
    expected_invocation_id: LifecycleExpectedInvocationId,
    staged_worker_path: LifecycleStagedWorkerPath,
    staged_worker_sha256: LifecycleStagedWorkerSha256,
    base_python: LifecycleBasePython,
    python_base_prefix: LifecyclePythonBasePrefix,
    agent_os_sid: LifecycleAgentOsSid,
    acl_paths_json: LifecycleAclPathsJson = None,
    cleanup_tool_roots_json: LifecycleCleanupToolRootsJson = None,
    owned_compiler_helper_roots: LifecycleOwnedCompilerHelperRoots = None,
    replay_patch: LifecycleReplayPatch = None,
    evaluator_container_config: LifecycleEvaluatorContainerConfig = None,
    agent_container_config: LifecycleAgentContainerConfig = None,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: CopilotModel = "gpt-5.6-luna",
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "copilot_lifecycle_run",
    al_mcp: LifecycleAlMcp = False,
    al_lsp: LifecycleAlLsp = False,
    bc_mcp: LifecycleBcMcp = False,
) -> None:
    """Run GitHub Copilot CLI through the checkpointed single-container bug-fix lifecycle."""
    _run_lifecycle(
        entry_id=entry_id,
        entry_root=entry_root,
        protected_root=protected_root,
        replay_patch=replay_patch,
        agent_os_username=agent_os_username,
        agent_os_password=agent_os_password,
        agent_bc_username=agent_bc_username,
        agent_bc_password=agent_bc_password,
        expected_container_id=expected_container_id,
        expected_invocation_id=expected_invocation_id,
        staged_worker_path=staged_worker_path,
        staged_worker_sha256=staged_worker_sha256,
        base_python=base_python,
        python_base_prefix=python_base_prefix,
        agent_os_sid=agent_os_sid,
        acl_paths_json=acl_paths_json,
        cleanup_tool_roots_json=cleanup_tool_roots_json,
        owned_compiler_helper_roots=owned_compiler_helper_roots,
        evaluator_container_config=evaluator_container_config,
        agent_container_config=agent_container_config,
        container_name=container_name,
        username=username,
        password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        model=model,
        output_dir=output_dir,
        run_id=run_id,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
        agent_name=AgentHarness.COPILOT,
        agent_version=get_copilot_version,
        agent_runner=lambda context, execution_policy, runtime, agent_output_dir: run_copilot_agent(
            entry=context.entry,
            repo_path=context.repo_path,
            category=_CATEGORY,
            model=context.model,
            output_dir=agent_output_dir,
            runtime=runtime,
            execution_policy=execution_policy,
        ),
    )


@bugfix_lifecycle_app.command("claude")
def bugfix_lifecycle_claude(
    entry_id: Annotated[str, typer.Argument(help="Bug-fix entry ID to evaluate")],
    entry_root: LifecycleEntryRoot,
    protected_root: LifecycleProtectedRoot,
    agent_os_username: LifecycleAgentOsUsername,
    agent_os_password: LifecycleAgentOsPassword,
    agent_bc_username: LifecycleAgentBcUsername,
    agent_bc_password: LifecycleAgentBcPassword,
    expected_container_id: LifecycleExpectedContainerId,
    expected_invocation_id: LifecycleExpectedInvocationId,
    staged_worker_path: LifecycleStagedWorkerPath,
    staged_worker_sha256: LifecycleStagedWorkerSha256,
    base_python: LifecycleBasePython,
    python_base_prefix: LifecyclePythonBasePrefix,
    agent_os_sid: LifecycleAgentOsSid,
    acl_paths_json: LifecycleAclPathsJson = None,
    cleanup_tool_roots_json: LifecycleCleanupToolRootsJson = None,
    owned_compiler_helper_roots: LifecycleOwnedCompilerHelperRoots = None,
    replay_patch: LifecycleReplayPatch = None,
    evaluator_container_config: LifecycleEvaluatorContainerConfig = None,
    agent_container_config: LifecycleAgentContainerConfig = None,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: ClaudeCodeModel = "claude-haiku-4-5",
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    run_id: RunId = "claude_lifecycle_run",
    al_mcp: LifecycleAlMcp = False,
    al_lsp: LifecycleAlLsp = False,
    bc_mcp: LifecycleBcMcp = False,
) -> None:
    """Run Claude Code through the checkpointed single-container bug-fix lifecycle."""
    _run_lifecycle(
        entry_id=entry_id,
        entry_root=entry_root,
        protected_root=protected_root,
        replay_patch=replay_patch,
        agent_os_username=agent_os_username,
        agent_os_password=agent_os_password,
        agent_bc_username=agent_bc_username,
        agent_bc_password=agent_bc_password,
        expected_container_id=expected_container_id,
        expected_invocation_id=expected_invocation_id,
        staged_worker_path=staged_worker_path,
        staged_worker_sha256=staged_worker_sha256,
        base_python=base_python,
        python_base_prefix=python_base_prefix,
        agent_os_sid=agent_os_sid,
        acl_paths_json=acl_paths_json,
        cleanup_tool_roots_json=cleanup_tool_roots_json,
        owned_compiler_helper_roots=owned_compiler_helper_roots,
        evaluator_container_config=evaluator_container_config,
        agent_container_config=agent_container_config,
        container_name=container_name,
        username=username,
        password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        model=model,
        output_dir=output_dir,
        run_id=run_id,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
        agent_name=AgentHarness.CLAUDE,
        agent_version=get_claude_version,
        agent_runner=lambda context, execution_policy, runtime, agent_output_dir: run_claude_code(
            entry=context.entry,
            repo_path=context.repo_path,
            category=_CATEGORY,
            model=context.model,
            output_dir=agent_output_dir,
            runtime=runtime,
            execution_policy=execution_policy,
        ),
    )


def _run_lifecycle(
    *,
    entry_id: str,
    entry_root: Path,
    protected_root: Path,
    replay_patch: Path | None,
    agent_os_username: str,
    agent_os_password: str,
    agent_bc_username: str,
    agent_bc_password: str,
    expected_container_id: str,
    expected_invocation_id: str,
    staged_worker_path: Path,
    staged_worker_sha256: str,
    base_python: Path,
    python_base_prefix: Path,
    agent_os_sid: str,
    acl_paths_json: str | None,
    cleanup_tool_roots_json: str | None,
    owned_compiler_helper_roots: list[Path] | None,
    evaluator_container_config: str | None,
    agent_container_config: str | None,
    container_name: str,
    username: str,
    password: str,
    server_url: str,
    server_instance: str,
    mcp_url: str | None,
    company: str,
    model: str,
    output_dir: Path,
    run_id: str,
    al_mcp: bool,
    al_lsp: bool,
    bc_mcp: bool,
    agent_name: AgentHarness,
    agent_version: Callable[[], str],
    agent_runner: LifecycleAgentInvoker,
) -> None:
    raw_cleanup = RawSetupCleanup(
        instance_id=entry_id,
        container_name=container_name,
        expected_container_id=expected_container_id,
        expected_invocation_id=expected_invocation_id,
        agent_os_username=agent_os_username,
        agent_bc_username=agent_bc_username,
        agent_os_sid=agent_os_sid,
        entry_root=entry_root,
        protected_root=protected_root,
        staged_worker_path=staged_worker_path,
        base_python=base_python,
        python_base_prefix=python_base_prefix,
        acl_paths_json=acl_paths_json,
        cleanup_tool_roots_json=cleanup_tool_roots_json,
        owned_compiler_helper_roots=tuple(owned_compiler_helper_roots or ()),
    )
    try:
        resources = _parse_setup_ownership_envelope(
            entry_id=entry_id,
            entry_root=entry_root,
            protected_root=protected_root,
            container_name=container_name,
            expected_container_id=expected_container_id,
            expected_invocation_id=expected_invocation_id,
            agent_os_username=agent_os_username,
            agent_bc_username=agent_bc_username,
            agent_os_sid=agent_os_sid,
            staged_worker_path=staged_worker_path,
            base_python=base_python,
            python_base_prefix=python_base_prefix,
            acl_paths_json=acl_paths_json,
            cleanup_tool_roots_json=cleanup_tool_roots_json,
            owned_compiler_helper_roots=owned_compiler_helper_roots,
        )
    except BaseException as error:
        cleanup_error = raw_cleanup.run(error)
        if cleanup_error is not None:
            raise cleanup_error from error
        raise

    cleanup_lease = CleanupLease.for_cli(resources)
    try:
        _run_lifecycle_after_lease(
            cleanup_lease=cleanup_lease,
            entry_id=entry_id,
            entry_root=entry_root,
            protected_root=protected_root,
            replay_patch=replay_patch,
            agent_os_username=agent_os_username,
            agent_os_password=agent_os_password,
            agent_bc_username=agent_bc_username,
            agent_bc_password=agent_bc_password,
            expected_container_id=expected_container_id,
            expected_invocation_id=expected_invocation_id,
            staged_worker_path=staged_worker_path,
            staged_worker_sha256=staged_worker_sha256,
            base_python=base_python,
            python_base_prefix=python_base_prefix,
            agent_os_sid=agent_os_sid,
            acl_paths_json=acl_paths_json,
            cleanup_tool_roots_json=cleanup_tool_roots_json,
            owned_compiler_helper_roots=owned_compiler_helper_roots,
            evaluator_container_config=evaluator_container_config,
            agent_container_config=agent_container_config,
            container_name=container_name,
            username=username,
            password=password,
            server_url=server_url,
            server_instance=server_instance,
            mcp_url=mcp_url,
            company=company,
            model=model,
            output_dir=output_dir,
            run_id=run_id,
            al_mcp=al_mcp,
            al_lsp=al_lsp,
            bc_mcp=bc_mcp,
            agent_name=agent_name,
            agent_version=agent_version,
            agent_runner=agent_runner,
        )
    except BaseException as error:
        cleanup_error = cleanup_lease.cleanup_as_cli(lambda: LifecycleCleanup.from_resources(cleanup_lease.resources).run())
        if cleanup_error is not None:
            raise cleanup_error from error
        raise


def _run_lifecycle_after_lease(
    *,
    cleanup_lease: CleanupLease,
    entry_id: str,
    entry_root: Path,
    protected_root: Path,
    replay_patch: Path | None,
    agent_os_username: str,
    agent_os_password: str,
    agent_bc_username: str,
    agent_bc_password: str,
    expected_container_id: str,
    expected_invocation_id: str,
    staged_worker_path: Path,
    staged_worker_sha256: str,
    base_python: Path,
    python_base_prefix: Path,
    agent_os_sid: str,
    acl_paths_json: str | None,
    cleanup_tool_roots_json: str | None,
    owned_compiler_helper_roots: list[Path] | None,
    evaluator_container_config: str | None,
    agent_container_config: str | None,
    container_name: str,
    username: str,
    password: str,
    server_url: str,
    server_instance: str,
    mcp_url: str | None,
    company: str,
    model: str,
    output_dir: Path,
    run_id: str,
    al_mcp: bool,
    al_lsp: bool,
    bc_mcp: bool,
    agent_name: AgentHarness,
    agent_version: Callable[[], str],
    agent_runner: LifecycleAgentInvoker,
) -> None:
    paths = _validated_paths(entry_root, protected_root)
    _validate_worker(staged_worker_path, staged_worker_sha256, paths)
    _require_file(base_python, "--base-python")
    run_id = _safe_run_id(run_id)
    run_dir_path = absolute_path(output_dir / run_id)
    try:
        require_disjoint(run_dir_path, paths.entry_root, "result run directory", "entry_root")
        require_disjoint(run_dir_path, paths.protected_root, "result run directory", "protected_root")
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--output-dir/--run-id") from error
    expected_container_id = _required(expected_container_id, "--expected-container-id")
    expected_invocation_id = _required(expected_invocation_id, "--expected-invocation-id")
    agent_os_username = _setup_owned_username(
        agent_os_username,
        "--agent-os-username",
        _SETUP_OS_USERNAME,
        "OS",
    )
    agent_os_password = _required(agent_os_password, "--agent-os-password")
    agent_bc_username = _setup_owned_username(
        agent_bc_username,
        "--agent-bc-username",
        _SETUP_BC_USERNAME,
        "BC",
    )
    agent_bc_password = _required(agent_bc_password, "--agent-bc-password")

    evaluator_fallback = _container_from_options(
        name=container_name,
        username=username,
        password=password,
        company=company,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        param_hint="BC_SERVER_*",
    )
    agent_fallback = ContainerConfig(
        name=evaluator_fallback.name,
        username=agent_bc_username,
        password=agent_bc_password,
        company=evaluator_fallback.company,
        server_url=evaluator_fallback.server_url,
        server_instance=evaluator_fallback.server_instance,
        mcp_url=evaluator_fallback.mcp_url,
    )
    evaluator_container, agent_container = _resolve_container_configs(
        evaluator_container_config,
        agent_container_config,
        evaluator_fallback,
        agent_fallback,
    )
    _validate_distinct_credentials(
        evaluator_container,
        agent_os_username,
        agent_os_password,
        agent_container,
    )
    try:
        agent_runtime = AgentRuntimeConfig(
            container=agent_container,
            al_mcp=al_mcp,
            al_lsp=al_lsp,
            bc_mcp=bc_mcp,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--bc-mcp") from error

    owned_roots = tuple(OwnedLifecycleRoot(path, expected_invocation_id) for path in owned_compiler_helper_roots or ())
    try:
        resources = ProvisionedLifecycleResources(
            instance_id=entry_id,
            paths=paths,
            container_name=evaluator_container.name,
            expected_container_id=expected_container_id,
            expected_container_invocation_id=expected_invocation_id,
            agent_os_username=agent_os_username,
            agent_bc_username=agent_bc_username,
            agent_os_sid=agent_os_sid,
            benchmark_root=Path(__file__).parents[3],
            staged_worker_path=staged_worker_path,
            base_python=base_python,
            python_base_prefix=python_base_prefix,
            cleanup_tool_roots=_parse_path_list(
                cleanup_tool_roots_json,
                "--cleanup-tool-roots-json",
            ),
            acl_paths=_parse_path_list(acl_paths_json, "--acl-paths-json"),
            compiler_helper_roots=owned_roots,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    cleanup_lease.replace_resources(resources)
    _run_lifecycle_with_cleanup_lease(
        cleanup_lease=cleanup_lease,
        replay_patch=replay_patch,
        staged_worker_sha256=staged_worker_sha256,
        agent_os_password=agent_os_password,
        evaluator_container=evaluator_container,
        agent_runtime=agent_runtime,
        model=model,
        output_dir=output_dir,
        run_id=run_id,
        agent_name=agent_name,
        agent_version=agent_version,
        agent_runner=agent_runner,
    )


def _run_lifecycle_with_cleanup_lease(
    *,
    cleanup_lease: CleanupLease,
    replay_patch: Path | None,
    staged_worker_sha256: str,
    agent_os_password: str,
    evaluator_container: ContainerConfig,
    agent_runtime: AgentRuntimeConfig,
    model: str,
    output_dir: Path,
    run_id: str,
    agent_name: AgentHarness,
    agent_version: Callable[[], str],
    agent_runner: LifecycleAgentInvoker,
) -> None:
    try:
        resources = validate_provisioned_lifecycle_resources(cleanup_lease.resources)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--acl-paths-json") from error
    cleanup_lease.replace_resources(resources)
    paths = resources.paths
    if replay_patch is not None:
        try:
            replay_patch = require_strict_descendant(replay_patch, paths.protected_root, "replay patch", "protected root")
        except ValueError as error:
            raise typer.BadParameter(str(error), param_hint="--replay-patch") from error
        _require_file(replay_patch, "--replay-patch")

    profile_environment = _prepare_agent_profile(paths)
    entry = BugFixEntry.load(_CATEGORY.dataset_path, entry_id=resources.instance_id)[0]
    resolved_agent_version = agent_version()
    run_dir = prepare_run_dir(output_dir, run_id)
    context = EvaluationContext(
        entry=entry,
        repo_path=paths.baseline_workspace,
        result_dir=run_dir,
        container=evaluator_container,
        model=model,
        agent_name=agent_name,
        agent_version=resolved_agent_version,
        category=_CATEGORY,
    )
    execution_policy = AgentExecutionPolicy(
        contain_process_tree=True,
        restricted_identity=WindowsIdentity(resources.agent_os_username, agent_os_password),
        allowlist_environment=True,
        python_executable=resources.base_python,
        worker_path=resources.staged_worker_path,
        worker_sha256=staged_worker_sha256.lower(),
        environment_overrides=profile_environment,
    )
    try:
        request = BugFixLifecycleRequest(
            context=context,
            provisioned_resources=resources,
            evaluator_container=evaluator_container,
            agent_runtime=agent_runtime,
            agent_execution_policy=execution_policy,
            replay_patch=replay_patch,
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error
    lifecycle = ProductionBugFixLifecycle.from_request(request)
    cleanup_lease.transfer_to_lifecycle()
    lifecycle.run(
        request,
        lambda agent_context, policy: agent_runner(agent_context, policy, agent_runtime, paths.agent_logs),
        cleanup_lease,
    )


def _parse_setup_ownership_envelope(
    *,
    entry_id: str,
    entry_root: Path,
    protected_root: Path,
    container_name: str,
    expected_container_id: str,
    expected_invocation_id: str,
    agent_os_username: str,
    agent_bc_username: str,
    agent_os_sid: str,
    staged_worker_path: Path,
    base_python: Path,
    python_base_prefix: Path,
    acl_paths_json: str | None,
    cleanup_tool_roots_json: str | None,
    owned_compiler_helper_roots: list[Path] | None,
) -> ProvisionedLifecycleResources:
    expected_container_id = _required(expected_container_id, "--expected-container-id")
    expected_invocation_id = _required(expected_invocation_id, "--expected-invocation-id")
    agent_os_username = _setup_owned_username(
        agent_os_username,
        "--agent-os-username",
        _SETUP_OS_USERNAME,
        "OS",
    )
    agent_bc_username = _setup_owned_username(
        agent_bc_username,
        "--agent-bc-username",
        _SETUP_BC_USERNAME,
        "BC",
    )
    try:
        return ProvisionedLifecycleResources(
            instance_id=_required(entry_id, "ENTRY_ID"),
            paths=_lifecycle_paths(entry_root, protected_root),
            container_name=_required(container_name, "--container-name"),
            expected_container_id=expected_container_id,
            expected_container_invocation_id=expected_invocation_id,
            agent_os_username=agent_os_username,
            agent_bc_username=agent_bc_username,
            agent_os_sid=agent_os_sid,
            benchmark_root=Path(__file__).parents[3],
            staged_worker_path=staged_worker_path,
            base_python=base_python,
            python_base_prefix=python_base_prefix,
            cleanup_tool_roots=_parse_path_list(
                cleanup_tool_roots_json,
                "--cleanup-tool-roots-json",
            ),
            acl_paths=_parse_path_list(acl_paths_json, "--acl-paths-json"),
            compiler_helper_roots=tuple(OwnedLifecycleRoot(path, expected_invocation_id) for path in owned_compiler_helper_roots or ()),
        )
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


def _validated_paths(entry_root: Path, protected_root: Path) -> BugFixLifecyclePaths:
    _require_directory(entry_root, "--entry-root")
    _require_directory(protected_root, "--protected-root")
    try:
        return validate_lifecycle_paths(_lifecycle_paths(entry_root, protected_root))
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint="--entry-root/--protected-root") from error


def _lifecycle_paths(entry_root: Path, protected_root: Path) -> BugFixLifecyclePaths:
    return BugFixLifecyclePaths(
        entry_root=entry_root,
        baseline_workspace=entry_root / "baseline-workspace",
        agent_workspace=entry_root / "agent-workspace",
        agent_logs=entry_root / "agent-logs",
        agent_tools=entry_root / "agent-tools",
        mounted_staging=entry_root / "mounted-staging",
        evaluator_workspaces=entry_root / "evaluator-workspaces",
        evidence=entry_root / "evidence",
        protected_root=protected_root,
        trusted_source=protected_root / "trusted-source",
        checkpoints=protected_root / "checkpoints",
        final_results=protected_root / "final-results",
    )


def _validate_worker(worker_path: Path, worker_sha256: str, paths: BugFixLifecyclePaths) -> None:
    _require_file(worker_path, "--staged-worker-path")
    expected_path = paths.agent_tools / "contained_process_worker.py"
    if worker_path != expected_path:
        raise typer.BadParameter(f"Staged worker must use the setup path {expected_path}", param_hint="--staged-worker-path")
    normalized_hash = worker_sha256.strip().lower()
    if len(normalized_hash) != 64 or any(character not in "0123456789abcdef" for character in normalized_hash):
        raise typer.BadParameter("Staged worker hash must be a 64-character SHA-256", param_hint="--staged-worker-sha256")
    if sha256_file(worker_path) != normalized_hash:
        raise typer.BadParameter("Staged worker hash does not match the worker file", param_hint="--staged-worker-sha256")


def _require_file(path: Path, param_hint: str) -> None:
    try:
        reject_reparse_components(path, path)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint=param_hint) from error
    if not path.exists():
        raise typer.BadParameter(f"Path {path} does not exist", param_hint=param_hint)
    if not path.is_file() or path.is_symlink():
        raise typer.BadParameter(f"{param_hint.removeprefix('--').replace('-', ' ')} must be an existing regular file", param_hint=param_hint)


def _require_directory(path: Path, param_hint: str) -> None:
    try:
        reject_reparse_components(path, path)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint=param_hint) from error
    if not path.exists():
        raise typer.BadParameter(f"Path {path} does not exist", param_hint=param_hint)
    if not path.is_dir() or path.is_symlink():
        raise typer.BadParameter(f"{param_hint.removeprefix('--').replace('-', ' ')} must be an existing directory", param_hint=param_hint)


def _required(value: str | None, param_hint: str) -> str:
    normalized = "" if value is None else value.strip()
    if not normalized:
        raise typer.BadParameter("Value must not be empty", param_hint=param_hint)
    return normalized


def _setup_owned_username(
    username: str,
    param_hint: str,
    pattern: re.Pattern[str],
    identity_kind: str,
) -> str:
    normalized = _required(username, param_hint)
    if pattern.fullmatch(normalized) is None:
        raise typer.BadParameter(
            f"Agent {identity_kind} username must be a setup-owned {identity_kind} username",
            param_hint=param_hint,
        )
    return normalized


def _prepare_agent_profile(paths: BugFixLifecyclePaths) -> dict[str, str]:
    _require_directory(paths.agent_logs, "--entry-root")
    profile_environment = production_agent_profile_environment(paths.agent_logs)
    profile_directories = tuple(dict.fromkeys(Path(profile_environment[name]) for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")))
    try:
        for directory in profile_directories:
            reject_reparse_components(directory, paths.agent_logs)
            directory.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError) as error:
        raise typer.BadParameter(f"Could not prepare agent profile directories: {error}", param_hint="--entry-root") from error
    for directory in profile_directories:
        _require_directory(directory, "--entry-root")
    return profile_environment


def _safe_run_id(run_id: str) -> str:
    normalized = _required(run_id, "--run-id")
    if normalized in {".", ".."} or Path(normalized).name != normalized or "/" in normalized or "\\" in normalized:
        raise typer.BadParameter("Run ID must be a single path component", param_hint="--run-id")
    return normalized


def _container_from_options(
    *,
    name: str,
    username: str,
    password: str,
    company: str,
    server_url: str,
    server_instance: str,
    mcp_url: str | None,
    param_hint: str,
) -> ContainerConfig:
    values = {
        "name": name,
        "username": username,
        "password": password,
        "company": company,
        "server_url": server_url,
        "server_instance": server_instance,
    }
    missing = [field for field, value in values.items() if not value.strip()]
    if missing:
        raise typer.BadParameter(f"Complete evaluator container configuration is required; missing: {', '.join(missing)}", param_hint=param_hint)
    return ContainerConfig(
        name=name,
        username=username,
        password=password,
        company=company,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url.strip() if mcp_url is not None else None,
    )


def _resolve_container_configs(
    evaluator_json: str | None,
    agent_json: str | None,
    evaluator_fallback: ContainerConfig,
    agent_fallback: ContainerConfig,
) -> tuple[ContainerConfig, ContainerConfig]:
    if (evaluator_json is None) != (agent_json is None):
        raise typer.BadParameter(
            "Evaluator and agent container config JSON must be provided together",
            param_hint="--evaluator-container-config/--agent-container-config",
        )
    if evaluator_json is None or agent_json is None:
        return evaluator_fallback, agent_fallback

    evaluator = _parse_container_config(evaluator_json, "--evaluator-container-config")
    agent = _parse_container_config(agent_json, "--agent-container-config")
    if evaluator != evaluator_fallback:
        raise typer.BadParameter("Evaluator container config JSON does not match BC_SERVER_* and BC_COMPANY", param_hint="--evaluator-container-config")
    if agent != agent_fallback:
        raise typer.BadParameter("Agent container config JSON does not match the lifecycle agent credentials", param_hint="--agent-container-config")
    return evaluator, agent


def _parse_container_config(payload: str, param_hint: str) -> ContainerConfig:
    try:
        value: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise typer.BadParameter(f"Invalid container config JSON: {error}", param_hint=param_hint) from error
    try:
        return ContainerConfig(**_validated_container_config_value(value))
    except (TypeError, ValueError) as error:
        raise typer.BadParameter(f"Invalid container config JSON: {error}", param_hint=param_hint) from error


def _parse_path_list(payload: str | None, param_hint: str) -> tuple[Path, ...]:
    if payload is None:
        return ()
    try:
        value: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"{param_hint} must be valid JSON: {error}") from error
    if not isinstance(value, list) or not all(isinstance(path, str) and path.strip() for path in value):
        raise ValueError(f"{param_hint} must be a JSON list of non-empty paths")
    return tuple(Path(path) for path in cast(list[str], value))


def _validated_container_config_value(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise TypeError("container config must be a JSON object")
    if not all(isinstance(field, str) for field in value):
        raise TypeError("container config field names must be strings")
    string_mapping = cast(Mapping[str, object], value)
    expected_fields = {
        "name",
        "username",
        "password",
        "company",
        "server_url",
        "server_instance",
        "mcp_url",
    }
    if set(string_mapping) != expected_fields:
        raise ValueError(f"container config fields must be exactly: {', '.join(sorted(expected_fields))}")
    if not all(isinstance(string_mapping[field], str) for field in expected_fields):
        raise TypeError("container config fields must be strings")
    return cast(dict[str, str], dict(string_mapping))


def _validate_distinct_credentials(
    evaluator: ContainerConfig,
    agent_os_username: str,
    agent_os_password: str,
    agent: ContainerConfig,
) -> None:
    usernames = {
        evaluator.username.strip().casefold(),
        agent_os_username.strip().casefold(),
        agent.username.strip().casefold(),
    }
    if len(usernames) != 3:
        raise typer.BadParameter("Evaluator, agent OS, and agent BC identities must differ")
    if len({evaluator.password, agent_os_password, agent.password}) != 3:
        raise typer.BadParameter("Evaluator, agent OS, and agent BC passwords must differ")
