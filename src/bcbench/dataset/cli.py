"""CLI commands for dataset operations."""

import json
import os
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from bcbench.core.logger import get_logger
from bcbench.core.utils import DATASET_PATH, DATASET_SCHEMA_PATH
from bcbench.dataset.dataset_loader import load_dataset_entries
from bcbench.dataset.validate_schema import validate_entries, ValidationResult

logger = get_logger(__name__)

dataset_app = typer.Typer(help="Query and analyze dataset")


@dataset_app.command("validate")
def validate_dataset(
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    schema_path: Annotated[Path, typer.Option(help="Path to schema file")] = DATASET_SCHEMA_PATH,
):
    """Validate all entries in the dataset against the JSON schema."""
    results: list[ValidationResult] = validate_entries(dataset_path, schema_path)
    failures = [r for r in results if not r.success]

    logger.info(f"Total: {len(results)}, Success: {len(results) - len(failures)}, Failed: {len(failures)}")

    if failures:
        for error in failures:
            logger.error(f"  {error}")
        raise typer.Exit(code=1)


@dataset_app.command("versions")
def list_versions(
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    github_output: Annotated[Optional[str], typer.Option("--github-output", help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
):
    """Get unique environment_setup_version values from the dataset."""
    entries = load_dataset_entries(dataset_path)
    versions = sorted({e.environment_setup_version for e in entries if e.environment_setup_version})

    print(f"Found {len(versions)} unique version(s):")
    for version in versions:
        print(f"  - {version}")

    if github_output:
        _write_github_output(github_output, json.dumps(versions))


@dataset_app.command("list")
def list_entries(
    version: Annotated[Optional[str], typer.Option(help="Filter by environment setup version")] = None,
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    github_output: Annotated[Optional[str], typer.Option("--github-output", help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
):
    """List dataset entry IDs, optionally filtered by version."""
    dataset_entries = load_dataset_entries(dataset_path, version=version) if version else load_dataset_entries(dataset_path)
    entry_ids = [e.instance_id for e in dataset_entries]

    print(f"Found {len(entry_ids)} entry(ies){f' for version {version}' if version else ''}:")
    for entry_id in entry_ids:
        print(f"  - {entry_id}")

    if github_output:
        _write_github_output(github_output, json.dumps(entry_ids))


@dataset_app.command("view")
def view_entry(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to view")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
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
    info_table.add_row("Project Paths", "\n".join(entry.project_paths) if entry.project_paths else "N/A")

    console.print(Panel(info_table, title="[bold]Entry Information[/bold]", border_style="blue"))

    console.print("\n[bold cyan]Problem Statement:[/bold cyan]")
    console.print(Panel(entry.problem_statement or "[dim]Empty[/dim]", border_style="green"))

    console.print("\n[bold cyan]Hints:[/bold cyan]")
    console.print(Panel(entry.hints_text or "[dim]Empty[/dim]", border_style="yellow"))

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
            test_table.add_row(str(test.get("codeunitID", "N/A")), ", ".join(test.get("functionName", [])))
        console.print(test_table)
    else:
        console.print("[dim]No FAIL_TO_PASS tests[/dim]")

    console.print("\n[bold cyan]PASS_TO_PASS Tests:[/bold cyan]")
    if entry.pass_to_pass:
        test_table = Table()
        test_table.add_column("Codeunit ID", style="magenta")
        test_table.add_column("Functions", style="yellow")
        for test in entry.pass_to_pass:
            test_table.add_row(str(test.get("codeunitID", "N/A")), ", ".join(test.get("functionName", [])))
        console.print(test_table)
    else:
        console.print("[dim]No PASS_TO_PASS tests[/dim]")


def _write_github_output(name: str, value: str) -> None:
    """Write a value to GitHub Actions output."""
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")
