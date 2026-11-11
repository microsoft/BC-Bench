"""CLI commands for running agents."""

import logging
from typing import Annotated, cast

import typer
from bcbench_core.agent.harness import AgentRequest

from bcbench.agent import BCalBackendConfig, BCalHarness, ClaudeHarness, CopilotHarness, PRReviewHarness
from bcbench.agent.bcal import BCalAgentRuntime
from bcbench.cli_options import (
    AgentConfigPath,
    BCalInferenceProvider,
    BCalLlmBackend,
    BCalLlmEndpoint,
    BCalLlmProvider,
    BCalLlmWireApi,
    BCalRuntimeOption,
    BCalSdkApiKeyEnv,
    BCalSdkBaseUrl,
    BCalSdkMaxModelRequests,
    BCalSdkModel,
    BCalSdkProvider,
    BCalSdkReasoningEffort,
    BCalSdkTimeoutSeconds,
    ClaudeCodeModel,
    ContainerCompany,
    ContainerMcpUrl,
    ContainerName,
    ContainerPassword,
    ContainerServerInstance,
    ContainerServerUrl,
    ContainerUsername,
    CopilotModel,
    EvaluationCategoryOption,
    OutputDir,
    PRReviewEnginePath,
    RepoPath,
    TierOption,
    resolve_agent_runtime,
)
from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.evaluate import CodeReviewPipeline, NL2ALPipeline
from bcbench.paths import SHARED_CONFIG_FILE
from bcbench.types import AgentConfig, DatasetTier, EvaluationCategory, EvaluationContext

logger = logging.getLogger(__name__)
_config = get_config()

run_app = typer.Typer(help="Run agents on single dataset entry")


@run_app.command("copilot")
def run_copilot(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    tier: TierOption = DatasetTier.GOLD,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
    bc_mcp: Annotated[bool, typer.Option("--bc-mcp", help="Enable the Business Central MCP server")] = False,
    config_path: AgentConfigPath = SHARED_CONFIG_FILE,
) -> None:
    """
    Run GitHub Copilot CLI on a single entry to generate the category output.

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run copilot microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    runtime = resolve_agent_runtime(
        container_name=container_name,
        username=username,
        container_password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    entry = category.entry_class.load(category.dataset_path(tier), entry_id=entry_id)[0]
    agent_config = AgentConfig.from_file(config_path)
    harness = CopilotHarness(model=model, category=category, agent_config=agent_config, plugin_root=_config.paths.plugin_root, runtime=runtime)
    context = EvaluationContext(entry=entry, repo_path=repo_path, result_dir=output_dir, agent=harness.identity(), category=category, tier=tier, container=runtime.container if runtime else None)
    if (definition := category.definition) is None:
        # Transitional: remove once every category is migrated
        category.pipeline(agent_config).setup_workspace(entry, repo_path)
    else:
        definition.make(agent_config).prepare_workspace(context)
    harness.run(context.agent_request())


@run_app.command("claude")
def run_claude(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    category: EvaluationCategoryOption,
    tier: TierOption = DatasetTier.GOLD,
    container_name: ContainerName = "",
    username: ContainerUsername = "",
    password: ContainerPassword = "",
    server_url: ContainerServerUrl = "",
    server_instance: ContainerServerInstance = "",
    mcp_url: ContainerMcpUrl = None,
    company: ContainerCompany = "",
    model: ClaudeCodeModel = "claude-haiku-4-5",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    al_mcp: Annotated[bool, typer.Option("--al-mcp", help="Enable AL MCP server")] = False,
    al_lsp: Annotated[bool, typer.Option("--al-lsp", help="Enable AL LSP server")] = False,
    bc_mcp: Annotated[bool, typer.Option("--bc-mcp", help="Enable the Business Central MCP server")] = False,
    config_path: AgentConfigPath = SHARED_CONFIG_FILE,
) -> None:
    """
    Run Claude Code on a single entry to generate the category output.

    For full evaluation including building and running tests, use 'bcbench evaluate' instead.

    Example:
        uv run bcbench run claude microsoft__BCApps-5633 --category bug-fix --repo-path /path/to/BCApps
    """
    runtime = resolve_agent_runtime(
        container_name=container_name,
        username=username,
        container_password=password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    entry = category.entry_class.load(category.dataset_path(tier), entry_id=entry_id)[0]
    agent_config = AgentConfig.from_file(config_path)
    harness = ClaudeHarness(model=model, category=category, agent_config=agent_config, plugin_root=_config.paths.plugin_root, runtime=runtime)
    context = EvaluationContext(entry=entry, repo_path=repo_path, result_dir=output_dir, agent=harness.identity(), category=category, tier=tier, container=runtime.container if runtime else None)
    if (definition := category.definition) is None:
        # Transitional: remove once every category is migrated
        category.pipeline(agent_config).setup_workspace(entry, repo_path)
    else:
        definition.make(agent_config).prepare_workspace(context)
    harness.run(context.agent_request())


@run_app.command("pr-review")
def run_pr_review(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    model: CopilotModel = "gpt-5.6-luna",
    repo_path: RepoPath = _config.paths.testbed_path,
    output_dir: OutputDir = _config.paths.evaluation_results_path,
    engine_path: PRReviewEnginePath = None,
    min_severity: Annotated[str | None, typer.Option(help="AGENT_MINIMUM_SEVERITY floor (defaults to config)")] = None,
) -> None:
    """
    Run BC PR Review on a single code-review entry.

    This production-fidelity runner is fixed to the code-review category, while the same
    category can also run through the generic copilot and claude commands for cross-system
    comparison. Writes review.json without scoring; for full evaluation use
    'bcbench evaluate pr-review'. Requires a local BC-ALAgents checkout
    (--engine-path or BC_PR_REVIEW_ROOT), PowerShell 7+, and an authenticated
    Copilot CLI.

    Example:
        uv run bcbench run pr-review synthetic__style-018 --repo-path /path/to/testbed
    """
    category = EvaluationCategory.CODE_REVIEW
    entry = CodeReviewEntry.load(category.dataset_path(), entry_id=entry_id)[0]
    CodeReviewPipeline().setup_workspace(entry, repo_path)

    harness = PRReviewHarness(model=model, engine_path=engine_path, min_severity=min_severity)
    harness.run(AgentRequest(task=entry, work_dir=repo_path, output_dir=output_dir))


@run_app.command("bcal")
def run_bcal(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to run")],
    tier: TierOption = DatasetTier.GOLD,
    repo_path: RepoPath = _config.paths.evaluation_results_path,
    llm_command: Annotated[str | None, typer.Option(envvar="BCAL_LLM_COMMAND", help="External LLM command used by BCal")] = None,
    llm_model: Annotated[str | None, typer.Option(envvar="BCAL_LLM_MODEL", help="Optional model/deployment passed to BCal")] = None,
    agent_runtime: BCalRuntimeOption = BCalAgentRuntime.LEGACY,
    sdk_provider: BCalSdkProvider = None,
    sdk_base_url: BCalSdkBaseUrl = None,
    sdk_model: BCalSdkModel = None,
    sdk_api_key_env: BCalSdkApiKeyEnv = None,
    sdk_reasoning_effort: BCalSdkReasoningEffort = None,
    sdk_max_model_requests: BCalSdkMaxModelRequests = None,
    sdk_timeout_seconds: BCalSdkTimeoutSeconds = None,
    inference_provider: BCalInferenceProvider = None,
    llm_provider: BCalLlmProvider = None,
    llm_wire_api: BCalLlmWireApi = None,
    llm_backend: BCalLlmBackend = "external-command",
    llm_endpoint: BCalLlmEndpoint = None,
) -> None:
    """
    Run BCal dotnet tool on a single nl2al entry to generate AL code.

    For full evaluation, use 'bcbench evaluate bcal' instead.

    Example:
        uv run bcbench run bcal nl2al__job-budget-report-1
    """
    category = EvaluationCategory.NL2AL
    entry: NL2ALEntry = cast(NL2ALEntry, category.entry_class.load(category.dataset_path(tier), entry_id=entry_id)[0])
    backend = BCalBackendConfig(
        command=llm_command,
        model=llm_model,
        agent_runtime=agent_runtime,
        sdk_provider=sdk_provider,
        sdk_base_url=sdk_base_url,
        sdk_model=sdk_model,
        sdk_api_key_env=sdk_api_key_env,
        sdk_reasoning_effort=sdk_reasoning_effort,
        sdk_max_model_requests=sdk_max_model_requests,
        sdk_timeout_seconds=sdk_timeout_seconds,
        inference_provider=inference_provider,
        llm_provider=llm_provider,
        llm_wire_api=llm_wire_api,
        backend=llm_backend,
        endpoint=llm_endpoint,
    )
    backend.cli_args()
    NL2ALPipeline().setup_workspace(entry, repo_path)
    harness = BCalHarness(backend)
    harness.run(AgentRequest(task=entry, work_dir=repo_path, output_dir=repo_path))
