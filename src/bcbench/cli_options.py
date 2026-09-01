"""Reusable CLI option definitions for typer commands."""

from pathlib import Path
from typing import Annotated, Literal

import typer

from bcbench.types import AgentToolingConfig, ContainerConfig, EvaluationCategory

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

RunId = Annotated[str, typer.Option(envvar="GITHUB_RUN_ID", help="Unique identifier for this evaluation run")]

ContainerName = Annotated[str, typer.Option(envvar="BC_CONTAINER_NAME", help="BC container name")]

ContainerUsername = Annotated[str, typer.Option(envvar="BC_SERVER_USERNAME", help="Username for BC container")]

ContainerPassword = Annotated[str, typer.Option(envvar="BC_SERVER_PASSWORD", help="Password for BC container")]

ContainerServerUrl = Annotated[str, typer.Option(envvar="BC_SERVER_URL", help="BC server URL")]

ContainerServerInstance = Annotated[str, typer.Option(envvar="BC_SERVER_INSTANCE", help="BC server instance")]

ContainerMcpUrl = Annotated[str | None, typer.Option(envvar="BC_MCP_URL", help="BC MCP upstream URL")]

ContainerCompany = Annotated[str | None, typer.Option(envvar="BC_COMPANY", help="BC company name")]

EvaluationCategoryOption = Annotated[EvaluationCategory, typer.Option(help="Category of evaluation to perform")]


def resolve_agent_tooling(
    *,
    category: EvaluationCategory,
    container_name: str,
    username: str,
    container_password: str,
    server_url: str,
    server_instance: str,
    mcp_url: str | None,
    company: str | None,
    al_mcp: bool,
    al_lsp: bool,
    bc_mcp: bool,
    for_evaluation: bool,
) -> AgentToolingConfig:
    container_name = container_name.strip()
    mcp_url = mcp_url.strip() or None if mcp_url is not None else None
    company = company.strip() or None if company is not None else None
    container_values = (username, container_password, server_url, server_instance, mcp_url, company)
    if not container_name and any(container_values):
        raise typer.BadParameter("Container options require --container-name", param_hint="--container-name")

    container = ContainerConfig(container_name, username, container_password, server_url, server_instance, mcp_url, company) if container_name else None

    if for_evaluation and category.requires_container and container is None:
        raise typer.BadParameter(f"The {category.value} category requires a container", param_hint="--container-name")
    if for_evaluation and category is EvaluationCategory.DATA_QUERY and not company:
        raise typer.BadParameter("The data-query category requires a company", param_hint="--company")

    try:
        return AgentToolingConfig(al_mcp=al_mcp, al_lsp=al_lsp, bc_mcp=bc_mcp, container=container)
    except ValueError as error:
        raise typer.BadParameter(str(error)) from error


CopilotModelName = Literal[
    "claude-sonnet-5",
    "claude-opus-5",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.3-codex",
    "mai-code-1.1-flash",
    "gemini-3.6-flash",
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
