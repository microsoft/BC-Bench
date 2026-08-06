"""Reusable CLI option definitions for typer commands."""

from pathlib import Path
from typing import Annotated, Literal

import typer

from bcbench.types import EvaluationCategory

# Type aliases for cleaner command signatures
# Note: Defaults are provided in function signatures, not here
RepoPath = Annotated[Path, typer.Option(help="Path to repository")]

OutputDir = Annotated[Path, typer.Option(help="Directory to save evaluation results", file_okay=False, dir_okay=True)]

RunId = Annotated[str, typer.Option(envvar="GITHUB_RUN_ID", help="Unique identifier for this evaluation run")]

ContainerName = Annotated[str, typer.Option(envvar="BC_CONTAINER_NAME", help="BC container name")]

ContainerUsername = Annotated[str, typer.Option(envvar="BC_SERVER_USERNAME", help="Username for BC container")]

ContainerPassword = Annotated[str, typer.Option(envvar="BC_SERVER_PASSWORD", help="Password for BC container")]

EvaluationCategoryOption = Annotated[EvaluationCategory, typer.Option(help="Category of evaluation to perform")]

CopilotModel = Annotated[
    Literal[
        "claude-sonnet-5",
        "claude-opus-5",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.3-codex",
        "mai-code-1-flash-picker",
        "gemini-3.6-flash",
    ],
    typer.Option(help="Copilot model to use"),
]

ClaudeCodeModel = Annotated[
    Literal[
        "claude-sonnet-5",
        "claude-opus-5",
        "claude-haiku-4-5",
    ],
    typer.Option(help="Claude Code model to use"),
]
