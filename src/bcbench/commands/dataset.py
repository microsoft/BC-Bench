"""CLI commands for dataset operations."""

import json
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.cli_options import DatasetPath
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.dataset.counterfactual_loader import load_counterfactual_entries
from bcbench.dataset.dataset_loader import load_dataset_entries
from bcbench.dataset.reviewer import run_dataset_reviewer
from bcbench.exceptions import ConfigurationError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()

dataset_app = typer.Typer(help="Query and analyze dataset")


@dataset_app.command("review")
def review_dataset(
    dataset_path: Annotated[Path, typer.Argument(help="Path to dataset JSONL file")] = _config.paths.dataset_path,
    results_dir: Annotated[
        Path | None, typer.Option("--results-dir", "-r", help="Directory containing result JSONL files to show resolution stats", exists=True, file_okay=False, dir_okay=True)
    ] = None,
):
    """
    Review dataset entries using a TUI.

    Opens a split-pane view showing entry information and problem statement.
    Use arrow keys to navigate between entries.

    If --results-dir is provided, shows resolution stats (e.g., "2/5 resolved")
    for each entry based on the results in that directory.
    """
    run_dataset_reviewer(dataset_path, results_dir)


@dataset_app.command("list")
def list_entries(
    dataset_path: DatasetPath = _config.paths.dataset_path,
    github_output: Annotated[str | None, typer.Option(help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    modified_only: Annotated[bool, typer.Option(help="Only list entries that have been modified in git diff")] = False,
    test_run: Annotated[bool, typer.Option(help="Indicate this is a test run (with 2 entries)")] = False,
    include_counterfactual: Annotated[bool, typer.Option(help="Include counterfactual entries from counterfactual.jsonl")] = True,
):
    """List dataset entry IDs."""
    if modified_only:
        import subprocess

        result = subprocess.run(
            [
                "git",
                "diff",
                "origin/main",
                "--unified=0",
                "--no-color",
                "--diff-filter=AM",
                "--",
                str(dataset_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            cwd=dataset_path.parent,
        )
        diff_output: str = result.stdout
        entry_ids: list[str] = _modified_instance_ids_from_diff(diff_output)

        if include_counterfactual:
            cf_path = dataset_path.parent / "counterfactual.jsonl"
            if cf_path.exists():
                cf_diff_result = subprocess.run(
                    [
                        "git",
                        "diff",
                        "origin/main",
                        "--unified=0",
                        "--no-color",
                        "--diff-filter=AM",
                        "--",
                        str(cf_path),
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True,
                    cwd=cf_path.parent,
                )
                entry_ids.extend(_modified_instance_ids_from_diff(cf_diff_result.stdout))
    else:
        dataset_entries: list[DatasetEntry] = load_dataset_entries(dataset_path, random=2 if test_run else None)
        entry_ids: list[str] = [e.instance_id for e in dataset_entries]

        if include_counterfactual:
            cf_path = dataset_path.parent / "counterfactual.jsonl"
            if cf_path.exists():
                cf_pairs = load_counterfactual_entries(cf_path, dataset_path)
                entry_ids.extend(cf_entry.instance_id for cf_entry, _ in cf_pairs)

    print(f"Found {len(entry_ids)} entry(ies){' (modified only)' if modified_only else ''}:")
    for entry_id in entry_ids:
        print(f"  - {entry_id}")

    if github_output:
        _write_github_output(github_output, json.dumps(entry_ids))


@dataset_app.command("view")
def view_entry(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to view")],
    dataset_path: DatasetPath = _config.paths.dataset_path,
    show_patch: Annotated[bool, typer.Option(help="Show patch in output")] = False,
):
    """View a specific dataset entry with rich formatting."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    entry = load_dataset_entries(dataset_path, entry_id=entry_id)[0]
    console = Console()

    info_table = Table(show_header=False, box=None)
    info_table.add_column("Field", style="cyan bold")
    info_table.add_column("Value")

    info_table.add_row("Repo", entry.repo or "N/A")
    info_table.add_row("Instance ID", entry.instance_id or "N/A")
    info_table.add_row("Base Commit", entry.base_commit or "N/A")
    info_table.add_row("Created At", entry.created_at or "N/A")
    info_table.add_row("Environment Setup Version", entry.environment_setup_version or "N/A")
    info_table.add_row(
        "Project Paths",
        "\n".join(entry.project_paths) if entry.project_paths else "N/A",
    )

    # Add metadata fields dynamically
    metadata_dict = entry.metadata.model_dump()
    for field_name, field_value in metadata_dict.items():
        display_name = field_name.replace("_", " ").title()
        info_table.add_row(f"[dim]Metadata:[/dim] {display_name}", str(field_value) if field_value else "N/A")

    console.print(Panel(info_table, title="[bold]Entry Information[/bold]", border_style="blue"))

    console.print("\n[bold cyan]Problem Statement with Hints:[/bold cyan]")
    console.print(Panel(entry.get_task() or "[dim]Empty[/dim]", border_style="green"))

    if show_patch:
        console.print("\n[bold cyan]Patch:[/bold cyan]")
        console.print(Panel(entry.patch or "[dim]Empty[/dim]", border_style="magenta"))
        console.print("\n[bold cyan]Test Patch:[/bold cyan]")
        console.print(Panel(entry.test_patch or "[dim]Empty[/dim]", border_style="magenta"))

    console.print("\n[bold cyan]FAIL_TO_PASS Tests:[/bold cyan]")
    if entry.fail_to_pass:
        test_table = Table()
        test_table.add_column("Codeunit ID", style="magenta")
        test_table.add_column("Functions", style="yellow")
        for test in entry.fail_to_pass:
            test_table.add_row(str(test.codeunitID), ", ".join(test.functionName))
        console.print(test_table)
    else:
        console.print("[dim]No FAIL_TO_PASS tests[/dim]")

    console.print("\n[bold cyan]PASS_TO_PASS Tests:[/bold cyan]")
    if entry.pass_to_pass:
        test_table = Table()
        test_table.add_column("Codeunit ID", style="magenta")
        test_table.add_column("Functions", style="yellow")
        for test in entry.pass_to_pass:
            test_table.add_row(
                str(test.codeunitID),
                ", ".join(test.functionName),
            )
        console.print(test_table)
    else:
        console.print("[dim]No PASS_TO_PASS tests[/dim]")


@dataset_app.command("cf-extract")
def cf_extract(
    entry_id: Annotated[str, typer.Argument(help="Base entry ID to extract workspace from")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to create workspace in")] = Path("cf-workspace"),
    repo_path: Annotated[Path | None, typer.Option("--repo-path", "-r", help="Repository path for full-fidelity extraction")] = None,
    dataset_path: DatasetPath = _config.paths.dataset_path,
):
    """Extract patch hunks into an editable workspace for counterfactual authoring."""
    from bcbench.dataset.cf_workspace import extract_workspace

    entries = load_dataset_entries(dataset_path, entry_id=entry_id)
    entry = entries[0]

    workspace = extract_workspace(entry, output_dir, repo_path)

    typer.echo(f"Workspace created at: {workspace}")
    typer.echo(f"  fix/after/   — edit these files to change the fix")
    typer.echo(f"  test/after/  — edit these files to change the tests")
    typer.echo(f"Run 'bcbench dataset cf-create {workspace}' when done editing.")


@dataset_app.command("cf-create")
def cf_create(
    workspace_dir: Annotated[Path, typer.Argument(help="Path to the workspace directory")],
    variant_description: Annotated[str, typer.Option("--variant-description", "-d", help="Description of the counterfactual variant")],
    intervention_type: Annotated[str | None, typer.Option("--intervention-type", "-t", help="Type of intervention")] = None,
):
    """Create a counterfactual entry from an edited workspace."""
    from bcbench.dataset.cf_workspace import create_cf_entry

    cf_entry = create_cf_entry(workspace_dir, variant_description, intervention_type)

    typer.echo(f"Created counterfactual entry: {cf_entry.instance_id}")
    typer.echo(f"Problem statement: {cf_entry.problem_statement_override}")
    typer.echo("Edit the problem statement README.md, then commit the changes.")


def _modified_instance_ids_from_diff(diff_output: str) -> list[str]:
    instance_ids = []

    for line in diff_output.splitlines():
        # Look for added or modified lines (lines starting with +)
        # Skip the diff header line (+++).
        if line.startswith("+") and not line.startswith("+++"):
            # Remove the leading '+' to get the actual content
            content: str = line[1:]

            entry_data = json.loads(content)
            instance_ids.append(entry_data["instance_id"])

    return instance_ids


def _write_github_output(key: str, value: str) -> None:
    """Write a value to GitHub Actions output."""
    config = get_config()
    if not config.env.github_output:
        raise ConfigurationError("GITHUB_OUTPUT environment variable not set. This feature is only available when running in GitHub Actions.")
    with open(config.env.github_output, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")
