"""CLI commands for collecting dataset entries."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.collection import ScreeningResult, collect_gh_entry, screen_gh_candidate
from bcbench.config import get_config
from bcbench.exceptions import CollectionError

_config = get_config()

collect_app = typer.Typer(help="Collect dataset entries from GitHub")


@collect_app.command("gh")
def collect_gh(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    output: Annotated[Path, typer.Option(help="Path to output dataset file")] = _config.paths.dataset_dir / "bcbench.jsonl",
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
):
    """
    Collect dataset entry from a GitHub pull request.

    Example usage:

    # Collect from default repo (microsoft/BCApps)
    bcbench collect gh 12345

    # Collect from custom repo
    bcbench collect gh 12345 --repo microsoft/AL
    """
    collect_gh_entry(pr_number=pr_number, output=output, repo=repo)


@collect_app.command("screen")
def screen(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to screen")],
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
):
    """
    Screen a GitHub PR as a dataset candidate for Bug-Fixing.

    Checks that the PR meets the minimum automated requirements for inclusion:
    - At least 2 project paths (fix project + test project)
    - Non-empty fix patch
    - At least one testable function in the test patch

    Stops at the first failure. Note: this is a preliminary filter only.
    A passing result still requires manual review.

    Example usage:

    # Screen a PR from default repo (microsoft/BCApps)
    bcbench collect screen 12345

    # Screen from custom repo
    bcbench collect screen 12345 --repo microsoft/AL
    """
    try:
        result: ScreeningResult = screen_gh_candidate(pr_number=pr_number, repo=repo)
    except CollectionError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    header = f"PR #{result.pr_number} from {result.repo}"
    if result.passed:
        typer.echo(f"{header}: PASSED")
        return

    typer.echo(f"{header}: FAILED - {result.reason}")
    raise typer.Exit(code=1)
