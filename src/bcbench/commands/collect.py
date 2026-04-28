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
def collect_screen(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to screen")],
    repo: Annotated[str, typer.Option(help="GitHub repository in OWNER/REPO format")] = "microsoft/BCApps",
):
    """
    Screen a GitHub pull request as a dataset candidate.

    Checks that the PR meets the minimum requirements for inclusion in the dataset:
    - At least 2 project paths (fix project + test project)
    - Non-empty fix patch
    - Non-empty test patch
    - At least one testable function in the test patch

    Exits with code 1 if the PR fails screening.

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

    _print_screening_result(result)

    if not result.passed:
        raise typer.Exit(code=1)


def _print_screening_result(result: ScreeningResult) -> None:
    typer.echo(f"\nScreening PR #{result.pr_number} from {result.repo}")
    typer.echo("-" * 50)

    typer.echo(f"Project paths ({len(result.project_paths)}):")
    for path in result.project_paths:
        typer.echo(f"  - {path}")

    typer.echo("")
    _print_check(">= 2 project paths", len(result.project_paths) >= 2, f"{len(result.project_paths)} found")
    _print_check("Fix patch present", result.has_fix_patch)
    _print_check("Test patch present", result.has_test_patch)
    _print_check("Testable functions found", result.fail_to_pass_count > 0, f"{result.fail_to_pass_count} found")

    typer.echo("")
    if result.passed:
        typer.echo("Result: PASSED - Suitable for dataset inclusion")
    else:
        typer.echo("Result: FAILED - Not suitable for dataset inclusion")
        for failure in result.failures:
            typer.echo(f"  - {failure}")


def _print_check(label: str, passed: bool, detail: str = "") -> None:
    mark = "✓" if passed else "✗"
    status = "PASS" if passed else "FAIL"
    detail_str = f" ({detail})" if detail else ""
    typer.echo(f"{mark} {label}: {status}{detail_str}")
