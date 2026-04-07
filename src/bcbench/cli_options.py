"""Reusable CLI option definitions for typer commands."""

from pathlib import Path
from typing import Annotated, Literal

import typer

from bcbench.types import EvaluationCategory

# Type aliases for cleaner command signatures
# Note: Defaults are provided in function signatures, not here
RepoPath = Annotated[Path, typer.Option(help="Path to repository")]

OutputDir = Annotated[Path, typer.Option(help="Directory to save evaluation results")]

RunId = Annotated[str, typer.Option(envvar="GITHUB_RUN_ID", help="Unique identifier for this evaluation run")]

ContainerName = Annotated[str, typer.Option(envvar="BC_CONTAINER_NAME", help="BC container name")]

ContainerUsername = Annotated[str, typer.Option(envvar="BC_CONTAINER_USERNAME", help="Username for BC container")]

ContainerPassword = Annotated[str, typer.Option(envvar="BC_CONTAINER_PASSWORD", help="Password for BC container")]

EvaluationCategoryOption = Annotated[EvaluationCategory, typer.Option(help="Category of evaluation to perform")]

CopilotModel = Annotated[
    Literal[
        "claude-sonnet-4.5",
        "claude-sonnet-4.6",
        "claude-haiku-4.5",
        "claude-opus-4.5",
        "claude-opus-4.6",
        "claude-opus-4.6-fast",
        "gpt-5.4",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-5.2",
        "gpt-4.1",
    ],
    typer.Option(help="Copilot model to use"),
]

FoundryModel = Annotated[
    Literal["gpt-5.1-codex-mini"],
    typer.Option(help="Microsoft Foundry Model to use"),
]

ClaudeCodeModel = Annotated[
    Literal[
        "claude-sonnet-4-6",
        "claude-opus-4-6",
        "claude-haiku-4-5",
    ],
    typer.Option(help="Claude Code model to use"),
]
