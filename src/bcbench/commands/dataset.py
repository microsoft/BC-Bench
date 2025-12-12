"""CLI commands for dataset operations."""

import json

import typer
from typing_extensions import Annotated

from bcbench.cli_options import DatasetPath
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.dataset.dataset_loader import load_dataset_entries
from bcbench.exceptions import ConfigurationError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()

dataset_app = typer.Typer(help="Query and analyze dataset")


@dataset_app.command("list")
def list_entries(
    dataset_path: DatasetPath = _config.paths.dataset_path,
    github_output: Annotated[str | None, typer.Option(help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    modified_only: Annotated[bool, typer.Option(help="Only list entries that have been modified in git diff")] = False,
    test_run: Annotated[bool, typer.Option(help="Indicate this is a test run (with 2 entries)")] = False,
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
    else:
        dataset_entries: list[DatasetEntry] = load_dataset_entries(dataset_path, random=2 if test_run else None)
        entry_ids: list[str] = [e.instance_id for e in dataset_entries]

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


@dataset_app.command("update-metadata")
def update_metadata(
    dataset_path: DatasetPath = _config.paths.dataset_path,
    dry_run: Annotated[bool, typer.Option(help="Print changes without writing to file")] = False,
):
    """Update metadata fields (e.g., image_count) for all dataset entries."""
    from typing import Any

    from rich.console import Console
    from rich.table import Table

    console = Console()
    entries = load_dataset_entries(dataset_path)

    updated_entries: list[dict[str, Any]] = []
    changes: list[tuple[str, int | None, int | None]] = []

    for entry in entries:
        # Count images in problem statement directory
        new_image_count = entry.count_images()
        old_image_count = entry.metadata.image_count

        # Create updated entry dict
        entry_dict = entry.model_dump(by_alias=True, mode="json")

        # Update metadata with new image_count
        entry_dict["metadata"]["image_count"] = new_image_count
        updated_entries.append(entry_dict)

        # Track changes
        if old_image_count != new_image_count:
            changes.append((entry.instance_id, old_image_count, new_image_count))

    # Display changes
    if changes:
        table = Table(title="Metadata Updates")
        table.add_column("Instance ID", style="cyan")
        table.add_column("Old image_count", style="red")
        table.add_column("New image_count", style="green")

        for instance_id, old_count, new_count in changes:
            table.add_row(instance_id, str(old_count), str(new_count))

        console.print(table)
        console.print(f"\n[bold]Total entries with changes: {len(changes)}[/bold]")
    else:
        console.print("[green]No changes needed - all metadata is up to date.[/green]")

    if dry_run:
        console.print("[yellow]Dry run - no changes written.[/yellow]")
        return

    # Write updated entries back to file
    with dataset_path.open("w", encoding="utf-8") as f:
        for entry_dict in updated_entries:
            json.dump(entry_dict, f, ensure_ascii=False)
            f.write("\n")

    console.print(f"[green]Updated {len(updated_entries)} entries in {dataset_path}[/green]")
