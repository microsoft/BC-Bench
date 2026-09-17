"""Reusable CLI option definitions for typer commands."""

from pathlib import Path
from typing import Annotated, Literal

import typer

from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationCategory

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
    ),
]

OutputDir = Annotated[Path, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)]

RunId = Annotated[str, typer.Option(envvar="GITHUB_RUN_ID", help="Unique identifier for this evaluation run")]

ContainerName = Annotated[str, typer.Option(envvar="BC_CONTAINER_NAME", help="BC container name")]

ContainerUsername = Annotated[str, typer.Option(envvar="BC_SERVER_USERNAME", help="Username for BC container")]

ContainerPassword = Annotated[
    str,
    typer.Option(
        envvar="BC_SERVER_PASSWORD",
        help="Password for BC container",
        hide_input=True,
        show_default=False,
    ),
]

ContainerServerUrl = Annotated[str, typer.Option(envvar="BC_SERVER_URL", help="BC server URL")]

ContainerServerInstance = Annotated[str, typer.Option(envvar="BC_SERVER_INSTANCE", help="BC server instance")]

ContainerMcpUrl = Annotated[str | None, typer.Option(envvar="BC_MCP_URL", help="BC MCP upstream URL")]

ContainerCompany = Annotated[str, typer.Option(envvar="BC_COMPANY", help="BC company name")]

EvaluationCategoryOption = Annotated[EvaluationCategory, typer.Option(help="Category of evaluation to perform")]

LifecycleEntryRoot = Annotated[
    Path,
    typer.Option(
        "--entry-root",
        envvar="BCBENCH_LIFECYCLE_ENTRY_ROOT",
        help="Setup-owned lifecycle entry root",
    ),
]

LifecycleProtectedRoot = Annotated[
    Path,
    typer.Option(
        "--protected-root",
        envvar="BCBENCH_LIFECYCLE_PROTECTED_ROOT",
        help="Evaluator-only protected lifecycle root",
    ),
]

LifecycleReplayPatch = Annotated[
    Path | None,
    typer.Option(
        "--replay-patch",
        envvar="BCBENCH_LIFECYCLE_REPLAY_PATCH",
        help="Protected patch to evaluate without running an agent",
    ),
]

LifecycleAgentOsUsername = Annotated[
    str,
    typer.Option(
        "--agent-os-username",
        envvar="BCBENCH_LIFECYCLE_AGENT_OS_USERNAME",
        help="Restricted local Windows agent username",
    ),
]

LifecycleAgentOsPassword = Annotated[
    str,
    typer.Option(
        "--agent-os-password",
        envvar="BCBENCH_LIFECYCLE_AGENT_OS_PASSWORD",
        help="Restricted local Windows agent password",
        hide_input=True,
        show_default=False,
    ),
]

LifecycleAgentBcUsername = Annotated[
    str,
    typer.Option(
        "--agent-bc-username",
        envvar="BCBENCH_LIFECYCLE_AGENT_BC_USERNAME",
        help="Restricted Business Central agent username",
    ),
]

LifecycleAgentBcPassword = Annotated[
    str,
    typer.Option(
        "--agent-bc-password",
        envvar="BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD",
        help="Restricted Business Central agent password",
        hide_input=True,
        show_default=False,
    ),
]

LifecycleExpectedContainerId = Annotated[
    str,
    typer.Option(
        "--expected-container-id",
        envvar="BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID",
        help="Owned container ID recorded by lifecycle setup",
    ),
]

LifecycleExpectedInvocationId = Annotated[
    str,
    typer.Option(
        "--expected-invocation-id",
        envvar="BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID",
        help="Owned lifecycle invocation ID recorded by setup",
    ),
]

LifecycleStagedWorkerPath = Annotated[
    Path,
    typer.Option(
        "--staged-worker-path",
        envvar="BCBENCH_LIFECYCLE_STAGED_WORKER_PATH",
        help="Setup-staged contained process worker",
    ),
]

LifecycleStagedWorkerSha256 = Annotated[
    str,
    typer.Option(
        "--staged-worker-sha256",
        envvar="BCBENCH_LIFECYCLE_STAGED_WORKER_SHA256",
        help="Expected SHA-256 of the staged contained process worker",
    ),
]

LifecycleBasePython = Annotated[
    Path,
    typer.Option(
        "--base-python",
        envvar="BCBENCH_LIFECYCLE_BASE_PYTHON",
        help="Setup-approved base Python executable",
    ),
]

LifecyclePythonBasePrefix = Annotated[
    Path,
    typer.Option(
        "--python-base-prefix",
        envvar="BCBENCH_LIFECYCLE_PYTHON_BASE_PREFIX",
        help="Exact setup-approved Python base prefix",
    ),
]

LifecycleAgentOsSid = Annotated[
    str,
    typer.Option(
        "--agent-os-sid",
        envvar="BCBENCH_LIFECYCLE_AGENT_OS_SID",
        help="Restricted Windows agent SID recorded by setup",
    ),
]

LifecycleAclPathsJson = Annotated[
    str | None,
    typer.Option(
        "--acl-paths-json",
        envvar="BCBENCH_LIFECYCLE_ACL_PATHS_JSON",
        help="Compact setup ACL transaction path list",
        show_default=False,
    ),
]

LifecycleCleanupToolRootsJson = Annotated[
    str | None,
    typer.Option(
        "--cleanup-tool-roots-json",
        envvar="BCBENCH_LIFECYCLE_CLEANUP_TOOL_ROOTS_JSON",
        help="Compact setup-approved cleanup tool root list",
        show_default=False,
    ),
]

LifecycleOwnedCompilerHelperRoots = Annotated[
    list[Path] | None,
    typer.Option(
        "--owned-compiler-helper-root",
        "--owned-compiler-root",
        "--owned-helper-root",
        envvar="BCBENCH_LIFECYCLE_OWNED_COMPILER_HELPER_ROOTS",
        help="Setup-owned compiler/helper root to remove during cleanup; repeat as needed",
    ),
]

LifecycleEvaluatorContainerConfig = Annotated[
    str | None,
    typer.Option(
        "--evaluator-container-config",
        envvar="BCBENCH_LIFECYCLE_EVALUATOR_CONTAINER_CONFIG",
        hidden=True,
        show_default=False,
    ),
]

LifecycleAgentContainerConfig = Annotated[
    str | None,
    typer.Option(
        "--agent-container-config",
        envvar="BCBENCH_LIFECYCLE_AGENT_CONTAINER_CONFIG",
        hidden=True,
        show_default=False,
    ),
]


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
