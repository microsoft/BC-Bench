"""Dataset query operations for CLI commands."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Set

import typer

from bcbench.dataset.dataset_loader import load_dataset_entries

__all__ = ["query_versions", "query_entries", "view_entry"]

logger = logging.getLogger(__name__)


def query_versions(
    dataset_path: Path,
    github_output: Optional[str] = None,
) -> List[str]:
    """
    Get unique environment setup versions from the dataset.

    Args:
        dataset_path: Path to the dataset file
        github_output: If provided, write to GITHUB_OUTPUT with this key name

    Returns:
        List of unique versions

    Raises:
        typer.Exit: Exits with code 1 on failure
    """
    if not dataset_path.exists():
        logger.error(f"Dataset file not found: {dataset_path}")
        raise typer.Exit(code=1)

    try:
        # Load all entries
        entries = load_dataset_entries(dataset_path)

        # Extract unique versions
        versions: Set[str] = set()
        for entry in entries:
            if entry.environment_setup_version:
                versions.add(entry.environment_setup_version)

    except Exception as exc:
        logger.error(f"Failed to read dataset file: {exc}")
        raise typer.Exit(code=1)

    # Convert to sorted list for consistent ordering
    version_list = sorted(versions)

    if not version_list:
        logger.error("No versions found in dataset")
        raise typer.Exit(code=1)

    # Display results to user
    print(f"Found {len(version_list)} unique version(s):")
    for version in version_list:
        print(f"  - {version}")

    # Write to GitHub Actions output if requested
    if github_output:
        _write_github_output(github_output, json.dumps(version_list))
        logger.info(f"Written to GITHUB_OUTPUT as '{github_output}'")

    return version_list


def query_entries(
    version: Optional[str],
    dataset_path: Path,
    github_output: Optional[str] = None,
) -> List[str]:
    """
    Get all instance IDs, optionally filtered by version.

    Args:
        version: Optional version to filter by. If None, returns all entries.
        dataset_path: Path to the dataset file
        github_output: If provided, write to GITHUB_OUTPUT with this key name

    Returns:
        List of instance IDs

    Raises:
        typer.Exit: Exits with code 1 on failure
    """
    if not dataset_path.exists():
        logger.error(f"Dataset file not found: {dataset_path}")
        raise typer.Exit(code=1)

    try:
        # Load all entries if no version filter, otherwise load filtered by version
        dataset_entries = load_dataset_entries(dataset_path, version=version) if version else load_dataset_entries(dataset_path)
        entries = [entry.instance_id for entry in dataset_entries]
    except ValueError:
        # load_dataset_entries raises ValueError when no entries match
        if version:
            logger.error(f"No entries found for version: {version}")
        else:
            logger.error("No entries found in dataset")
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.error(f"Failed to load dataset: {exc}")
        raise typer.Exit(code=1)

    if not entries:
        if version:
            logger.error(f"No entries found for version: {version}")
        else:
            logger.error("No entries found in dataset")
        raise typer.Exit(code=1)

    if version:
        print(f"Found {len(entries)} entry(ies) for version {version}:")
    else:
        print(f"Found {len(entries)} entry(ies) in dataset:")

    for entry_id in entries:
        print(f"  - {entry_id}")

    if github_output:
        _write_github_output(github_output, json.dumps(entries))
        logger.info(f"Written to GITHUB_OUTPUT as '{github_output}'")

    return entries


def view_entry(entry_id: str, dataset_path: Path, show_patch: bool) -> None:
    """
    View a specific dataset entry with rich formatting.

    Args:
        entry_id: The entry ID to view
        dataset_path: Path to the dataset file
        show_patch: Whether to show the patch in the output

    Raises:
        typer.Exit: Exits with code 1 on failure
    """
    if not dataset_path.exists():
        logger.error(f"Dataset file not found: {dataset_path}")
        raise typer.Exit(code=1)

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        # Load the specific entry
        entries = load_dataset_entries(dataset_path, entry_id=entry_id)
        entry = entries[0]  # load_dataset_entries returns a list with one entry when entry_id is specified

        console = Console()

        # Display all basic properties
        info_table = Table(show_header=False, box=None)
        info_table.add_column("Field", style="cyan bold")
        info_table.add_column("Value")

        info_table.add_row("Repo", entry.repo or "N/A")
        info_table.add_row("Instance ID", entry.instance_id or "N/A")
        info_table.add_row("Base Commit", entry.base_commit or "N/A")
        info_table.add_row("Created At", entry.created_at or "N/A")
        info_table.add_row("Version", entry.version or "N/A")
        info_table.add_row("Environment Setup Version", entry.environment_setup_version or "N/A")
        info_table.add_row("Project Paths", "\n".join(entry.project_paths) if entry.project_paths else "N/A")

        console.print(Panel(info_table, title="[bold]Entry Information[/bold]", border_style="blue"))

        # Display problem statement (always show, even if empty)
        console.print("\n[bold cyan]Problem Statement:[/bold cyan]")
        console.print(Panel(entry.problem_statement or "[dim]Empty[/dim]", border_style="green"))

        # Display hints (always show, even if empty)
        console.print("\n[bold cyan]Hints:[/bold cyan]")
        console.print(Panel(entry.hints_text or "[dim]Empty[/dim]", border_style="yellow"))

        if show_patch:
            console.print("\n[bold cyan]Patch:[/bold cyan]")
            if entry.patch:
                console.print(Panel(entry.patch, border_style="magenta"))
            else:
                console.print(Panel("[dim]Empty[/dim]", border_style="magenta"))

            console.print("\n[bold cyan]Test Patch:[/bold cyan]")
            if entry.test_patch:
                console.print(Panel(entry.test_patch, border_style="magenta"))
            else:
                console.print(Panel("[dim]Empty[/dim]", border_style="magenta"))

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

        # Display PASS_TO_PASS tests (always show, even if empty)
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

    except ValueError:
        # load_dataset_entries raises ValueError if entry_id not found
        logger.error(f"Entry not found: {entry_id}")
        raise typer.Exit(code=1)
    except ImportError:
        logger.error("Rich library not installed. Install with: pip install rich")
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.error(f"Failed to view entry: {exc}")
        raise typer.Exit(code=1)


def _write_github_output(name: str, value: str) -> None:
    """
    Write a value to GitHub Actions output.

    Args:
        name: The output variable name
        value: The output value

    Raises:
        typer.Exit: Exits with code 1 if GITHUB_OUTPUT is not set or write fails
    """
    github_output_file = os.environ.get("GITHUB_OUTPUT")
    if not github_output_file:
        logger.error("GITHUB_OUTPUT environment variable not set")
        raise typer.Exit(code=1)

    try:
        with open(github_output_file, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    except Exception as e:
        logger.error(f"Failed to write to GITHUB_OUTPUT: {e}")
        raise typer.Exit(code=1)
