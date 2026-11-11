"""Reusable CLI option definitions for typer commands."""

from pathlib import Path
from typing import Annotated, Literal

import typer
from bcbench_core.container import ContainerConfig

from bcbench.types import AgentRuntimeConfig, BCalAgentPlanning, BCalAgentRuntime, DatasetTier, EvaluationCategory

# Type aliases for cleaner command signatures
# Note: Defaults are provided in function signatures, not here
RepoPath = Annotated[Path, typer.Option(help="Path to repository")]

PRReviewEnginePath = Annotated[
    Path | None,
    typer.Option(
        "--engine-path",
        envvar="BC_PR_REVIEW_ROOT",
        help="Path to a local BC-ALAgents checkout",
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
    ),
]

OutputDir = Annotated[Path, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)]

AgentConfigPath = Annotated[Path, typer.Option("--config", help="Agent config file (prompts, instructions, skills, plugins, MCP)", exists=True, dir_okay=False, readable=True)]

RunId = Annotated[str, typer.Option(envvar="GITHUB_RUN_ID", help="Unique identifier for this evaluation run")]

ContainerName = Annotated[str, typer.Option(envvar="BC_CONTAINER_NAME", help="BC container name")]

ContainerUsername = Annotated[str, typer.Option(envvar="BC_SERVER_USERNAME", help="Username for BC container")]

ContainerPassword = Annotated[str, typer.Option(envvar="BC_SERVER_PASSWORD", help="Password for BC container")]

ContainerServerUrl = Annotated[str, typer.Option(envvar="BC_SERVER_URL", help="BC server URL")]

ContainerServerInstance = Annotated[str, typer.Option(envvar="BC_SERVER_INSTANCE", help="BC server instance")]

ContainerMcpUrl = Annotated[str | None, typer.Option(envvar="BC_MCP_URL", help="BC MCP upstream URL")]

ContainerCompany = Annotated[str, typer.Option(envvar="BC_COMPANY", help="BC company name")]

EvaluationCategoryOption = Annotated[EvaluationCategory, typer.Option(help="Category of evaluation to perform")]

TierOption = Annotated[DatasetTier, typer.Option(help="Only use dataset entries whose metadata.tier matches")]

BCalRuntimeOption = Annotated[BCalAgentRuntime, typer.Option("--agent-runtime", envvar="BCAL_AGENT_RUNTIME", help="BCal orchestration runtime; legacy remains the default")]
BCalPlanningOption = Annotated[
    BCalAgentPlanning | None, typer.Option("--agent-planning", help="Planning/self-review policy: SDK defaults to copilot; legacy requires bcal. No automatic fallback or environment override")
]
BCalSdkProvider = Annotated[Literal["openai"] | None, typer.Option("--sdk-provider", envvar="BCAL_SDK_PROVIDER", help="Explicit supported SDK provider type (Responses API)")]
BCalSdkBaseUrl = Annotated[str | None, typer.Option("--sdk-base-url", envvar="BCAL_SDK_BASE_URL", help="SDK provider base URL ending in /v1; never include credentials")]
BCalSdkModel = Annotated[str | None, typer.Option("--sdk-model", envvar="BCAL_SDK_MODEL", help="Explicit main SDK wire model; --llm-model remains legacy/auxiliary")]
BCalSdkApiKeyEnv = Annotated[str | None, typer.Option("--sdk-api-key-env", envvar="BCAL_SDK_API_KEY_ENV", help="Name of the environment variable holding the SDK provider key")]
BCalSdkReasoningEffort = Annotated[
    Literal["none", "low", "medium", "high", "xhigh", "max"] | None, typer.Option("--sdk-reasoning-effort", envvar="BCAL_SDK_REASONING_EFFORT", help="Explicit main SDK reasoning effort")
]
BCalSdkMaxModelRequests = Annotated[
    int | None, typer.Option("--sdk-max-model-requests", envvar="BCAL_SDK_MAX_MODEL_REQUESTS", min=1, help="SDK upstream HTTP admission cap, including retries/compaction; not tool calls")
]
BCalSdkTimeoutSeconds = Annotated[int | None, typer.Option("--sdk-timeout-seconds", envvar="BCAL_SDK_TIMEOUT_SECONDS", min=1, help="SDK session deadline in seconds")]
BCalInferenceProvider = Annotated[str | None, typer.Option("--inference-provider", envvar="BCAL_INFERENCE_PROVIDER", help="Non-secret main inference provider identity for result attribution")]
BCalLlmProvider = Annotated[str | None, typer.Option("--llm-provider", envvar="BCAL_LLM_PROVIDER", help="Non-secret legacy/auxiliary provider identity for attribution")]
BCalLlmWireApi = Annotated[
    Literal["chat-completions", "responses"] | None, typer.Option("--llm-wire-api", envvar="BCAL_LLM_WIRE_API", help="Actual legacy/auxiliary wire API, when known; metadata only")
]
BCalLlmBackend = Annotated[
    Literal["external-command", "azure-openai"], typer.Option("--llm-backend", envvar="BCAL_LLM_BACKEND", help="Legacy/auxiliary inference backend, independent of agent runtime")
]
BCalLlmEndpoint = Annotated[str | None, typer.Option("--llm-endpoint", envvar="BCAL_LLM_ENDPOINT", help="Explicit Azure OpenAI legacy/auxiliary endpoint")]


def resolve_agent_runtime(
    *,
    container_name: str,
    username: str,
    container_password: str,
    server_url: str,
    server_instance: str,
    mcp_url: str | None,
    company: str,
    al_mcp: bool,
    al_lsp: bool,
    bc_mcp: bool,
) -> AgentRuntimeConfig | None:
    """
    Resolve optional container and tooling options into validated runtime configuration.

    Mostly used for local development and testing. For CI runs, use `resolve_evaluation_runtime` instead, which enforces category-specific container requirements.
    """
    container_name = container_name.strip()
    mcp_url = mcp_url.strip() or None if mcp_url is not None else None
    container_values = (username, container_password, server_url, server_instance, mcp_url, company)
    if not container_name and any(container_values):
        raise typer.BadParameter("Container options require --container-name", param_hint="--container-name")
    if not container_name:
        if al_mcp or al_lsp or bc_mcp:
            raise typer.BadParameter("A container is required when AL MCP, AL LSP, or BC MCP is enabled", param_hint="--container-name")
        return None

    try:
        container = ContainerConfig(container_name, username, container_password, company, server_url, server_instance, mcp_url)
        return AgentRuntimeConfig(container=container, al_mcp=al_mcp, al_lsp=al_lsp, bc_mcp=bc_mcp)
    except ValueError as error:
        param_hint = "--company" if not company.strip() else "--mcp-url"
        raise typer.BadParameter(str(error), param_hint=param_hint) from error


def resolve_evaluation_runtime(
    *,
    category: EvaluationCategory,
    container_name: str,
    username: str,
    container_password: str,
    server_url: str,
    server_instance: str,
    mcp_url: str | None,
    company: str,
    al_mcp: bool,
    al_lsp: bool,
    bc_mcp: bool,
) -> AgentRuntimeConfig | None:
    """Resolve runtime configuration and enforce the category's container requirement."""
    runtime = resolve_agent_runtime(
        container_name=container_name,
        username=username,
        container_password=container_password,
        server_url=server_url,
        server_instance=server_instance,
        mcp_url=mcp_url,
        company=company,
        al_mcp=al_mcp,
        al_lsp=al_lsp,
        bc_mcp=bc_mcp,
    )
    if category.requires_container and runtime is None:
        raise typer.BadParameter(f"The {category.value} category requires a container", param_hint="--container-name")
    return runtime


CopilotModelName = Literal[
    "claude-sonnet-5",
    "claude-opus-5",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.3-codex",
    "mai-code-1.1-flash",
    "gemini-3.7-flash",
]

CopilotModel = Annotated[CopilotModelName, typer.Option(help="Copilot model to use")]

ClaudeCodeModel = Annotated[
    Literal[
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-4-5",
    ],
    typer.Option(help="Claude Code model to use"),
]
