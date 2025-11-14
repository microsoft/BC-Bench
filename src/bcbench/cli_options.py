"""Reusable CLI option definitions for typer commands."""

from pathlib import Path
from typing import Annotated, Literal

import typer

# Type aliases for cleaner command signatures
# Note: Defaults are provided in function signatures, not here
DatasetPath = Annotated[Path, typer.Option(help="Path to dataset file")]

RepoPath = Annotated[Path, typer.Option(help="Path to repository")]

SchemaPath = Annotated[Path, typer.Option(help="Path to schema file")]

OutputDir = Annotated[Path, typer.Option(help="Directory to save evaluation results")]

RunId = Annotated[str, typer.Option(envvar="GITHUB_RUN_ID", help="Unique identifier for this evaluation run")]

ContainerName = Annotated[str, typer.Option(envvar="BC_CONTAINER_NAME", help="BC container name")]

ContainerUsername = Annotated[str, typer.Option(envvar="BC_CONTAINER_USERNAME", help="Username for BC container")]

ContainerPassword = Annotated[str, typer.Option(envvar="BC_CONTAINER_PASSWORD", help="Password for BC container")]

CopilotModel = Annotated[Literal["claude-sonnet-4.5", "claude-sonnet-4", "claude-haiku-4.5", "gpt-5", "gpt-5.1", "gpt-5.1-codex-mini", "gpt-5.1-codex"], typer.Option(help="Copilot model to use")]
