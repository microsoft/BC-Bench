"""CLI commands for collecting dataset entries."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.collection import collect_nav_entry
from bcbench.utils import DATASET_PATH, NAV_REPO_PATH

collect_app = typer.Typer(help="Collect dataset entries from various sources")


@collect_app.command("nav")
def collect_nav(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    output: Annotated[Path, typer.Option(help="Output file path")] = DATASET_PATH,
    repo_path: Path = NAV_REPO_PATH,
    diff_path: Annotated[str, typer.Option(help="Filter git diff to only show changes under this path")] = "",
):
    """
    Collect dataset entry from Azure DevOps NAV pull request.

    Try it out with: bcbench collect nav 210528 --output dataset/bcbench_nav.jsonl

    For BaseApp Data, use diff_path: .\\App\\Layers\\W1\\:
    """
    collect_nav_entry(
        pr_number=pr_number,
        output=output,
        repo_path=repo_path,
        diff_path=diff_path,
    )
