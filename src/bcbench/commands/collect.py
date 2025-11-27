"""CLI commands for collecting dataset entries."""

import typer
from typing_extensions import Annotated

from bcbench.cli_options import DatasetPath, RepoPath
from bcbench.collection import collect_gh_entry, collect_nav_entry
from bcbench.config import get_config

_config = get_config()

collect_app = typer.Typer(help="Collect dataset entries from various sources")


@collect_app.command("nav")
def collect_nav(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    output: DatasetPath = _config.paths.dataset_path,
    repo_path: RepoPath = _config.paths.nav_repo_path,
    diff_path: Annotated[str, typer.Option(help="Filter git diff to only show changes under this path")] = "",
):
    """
    Collect dataset entry from Azure DevOps NAV pull request.

    Try it out with: bcbench collect nav 210528 --output dataset/bcbench_nav.jsonl

    For BaseApp Data, use diff_path: .\\App\\Layers\\W1\\:
    """
    collect_nav_entry(pr_number=pr_number, output=output, repo_path=repo_path, diff_path=diff_path)


@collect_app.command("gh")
def collect_gh(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    output: DatasetPath = _config.paths.dataset_path,
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
):
    """
    Collect dataset entry from public GitHub repositories.

    Example usage:

    # Collect from default repo (microsoft/BCApps)
    bcbench collect gh 12345

    # Collect from custom repo
    bcbench collect gh 12345 --repo microsoft/AL
    """
    collect_gh_entry(pr_number=pr_number, output=output, repo=repo)
