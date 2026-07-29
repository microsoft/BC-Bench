"""CLI commands for collecting dataset entries."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.collection import ScreeningResult, collect_codereview_entry, collect_gh_entry, screen_gh_candidate
from bcbench.config import get_config
from bcbench.exceptions import CollectionError

_config = get_config()

collect_app = typer.Typer(help="Collect dataset entries from GitHub")


@collect_app.command("gh")
def collect_gh(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    environment_setup_version: Annotated[
        str,
        typer.Option("--environment-setup-version", help="BC environment version to record on the entry (e.g. 28.0)"),
    ],
    output: Annotated[Path, typer.Option(help="Path to output dataset file")] = _config.paths.dataset_dir / "bcbench.jsonl",
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
) -> None:
    """
    Collect dataset entry from a GitHub pull request.

    Example usage:

    # Collect from default repo (microsoft/BCApps)
    bcbench collect gh 12345 --environment-setup-version 28.0

    # Collect from custom repo
    bcbench collect gh 12345 --repo microsoft/AL --environment-setup-version 28.0
    """
    collect_gh_entry(pr_number=pr_number, output=output, repo=repo, environment_setup_version=environment_setup_version)


@collect_app.command("codereview")
def collect_codereview(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    environment_setup_version: Annotated[
        str,
        typer.Option("--environment-setup-version", help="BC environment version to record on the entry (e.g. 27.0)"),
    ],
    output: Annotated[Path, typer.Option(help="Path to output dataset file")] = _config.paths.dataset_dir / "codereview.jsonl",
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
    reviewer: Annotated[
        str | None,
        typer.Option(help="Only use inline comments authored by this GitHub login as expected findings"),
    ] = None,
    reacted: Annotated[
        bool,
        typer.Option("--reacted", help="Only use comments with a positive reaction (thumbs-up / heart / ...) as expected findings"),
    ] = False,
    area: Annotated[str | None, typer.Option(help="Value to record in metadata.area")] = None,
) -> None:
    """
    Build a code-review dataset entry from a real GitHub pull request.

    The PR diff becomes the review patch; its inline comments become the expected
    findings. Choose which comments count as expected with --reviewer or --reacted
    (default: all top-level inline comments).

    Example usage:

    # A PR whose expected findings a reviewer wrote directly as inline comments
    bcbench collect codereview 9553 --reviewer WaelAbuSeada --environment-setup-version 27.0 --area privacy

    # Harvest online-eval reactions: any comment that got a thumbs-up (add
    # --reviewer <bot-login> to restrict to the review bot)
    bcbench collect codereview 9315 --reacted --environment-setup-version 27.0
    """
    try:
        entry = collect_codereview_entry(
            pr_number=pr_number,
            output=output,
            environment_setup_version=environment_setup_version,
            repo=repo,
            reviewer=reviewer,
            reacted=reacted,
            area=area,
        )
    except CollectionError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Saved {entry.instance_id} with {len(entry.expected_comments)} expected comment(s) to {output}")


@collect_app.command("screen")
def screen(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to screen")],
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
) -> None:
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
