import os
import sys
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.cli_options import EvaluationCategoryOption
from bcbench.types import EvaluationCategory

category_app = typer.Typer(help="Category-specific configuration helpers")


@category_app.command("list")
def list_categories() -> None:
    """Print all evaluation category names, one per line."""
    for category in EvaluationCategory:
        sys.stdout.write(f"{category.value}\n")


@category_app.command("bceval-config")
def bceval_config(
    category: EvaluationCategoryOption,
    github_output: Annotated[
        Path | None,
        typer.Option(envvar="GITHUB_OUTPUT", help="Append outputs to this file (typically $GITHUB_OUTPUT)"),
    ] = None,
) -> None:
    """
    Print the bc-eval evaluator list and core score for a category as key=value lines.

    When run inside a GitHub Actions step with $GITHUB_OUTPUT set, the lines are
    appended to that file so they become step outputs. Otherwise they're written
    to stdout.
    """
    lines: list[str] = [
        f"evaluators={','.join(category.evaluators)}",
        f"core_score={category.core_score}",
    ]
    payload: str = "\n".join(lines) + "\n"

    if github_output:
        with open(github_output, "a", encoding="utf-8") as file:
            file.write(payload)
    else:
        sys.stdout.write(payload)

    # Always echo to stderr so workflow logs show what was emitted.
    if os.getenv("GITHUB_ACTIONS"):
        sys.stderr.write(payload)
