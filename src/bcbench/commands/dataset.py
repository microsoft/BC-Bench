"""CLI commands for dataset operations."""

import json

import typer
from typing_extensions import Annotated

from bcbench.cli_options import EvaluationCategoryOption
from bcbench.dataset import BaseDatasetEntry, CodeReviewEntry
from bcbench.dataset.dataset_entry import NL2ALEntry, _BugFixTestGenBase
from bcbench.github_actions import write_step_outputs
from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

dataset_app = typer.Typer(help="Query and analyze dataset")


@dataset_app.command("list")
def list_entries(
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    github_output: Annotated[str | None, typer.Option(help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    modified_only: Annotated[bool, typer.Option(help="Only list entries that have been modified in git diff")] = False,
    test_run: Annotated[bool, typer.Option(help="Indicate this is a test run (with 2 entries)")] = False,
) -> None:
    """List dataset entry IDs."""
    entry_cls = category.entry_class
    resolved_path = category.dataset_path

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
                str(resolved_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            cwd=resolved_path.parent,
        )
        diff_output: str = result.stdout
        entry_ids: list[str] = _modified_instance_ids_from_diff(diff_output)
    else:
        entries: list[BaseDatasetEntry] = entry_cls.load(resolved_path, random=4 if test_run else None)
        entry_ids: list[str] = [e.instance_id for e in entries]

    print(f"Found {len(entry_ids)} entry(ies){' (modified only)' if modified_only else ''}:")
    for entry_id in entry_ids:
        print(f"  - {entry_id}")

    if github_output:
        write_step_outputs({github_output: json.dumps(entry_ids)})


@dataset_app.command("view")
def view_entry(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to view")],
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    show_patch: Annotated[bool, typer.Option(help="Show patch in output")] = False,
) -> None:
    """View a specific dataset entry with rich formatting."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    entry: BaseDatasetEntry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
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

    if isinstance(entry, NL2ALEntry):
        info_table.add_row("Page", entry.page)
        info_table.add_row("Audience", entry.audience)

    metadata_dict = entry.metadata.model_dump()
    for field_name, field_value in metadata_dict.items():
        if field_value is not None:
            display_name = field_name.replace("_", " ").title()
            info_table.add_row(f"[dim]Metadata:[/dim] {display_name}", str(field_value))

    console.print(Panel(info_table, title="[bold]Entry Information[/bold]", border_style="blue"))

    console.print("\n[bold cyan]Problem Statement with Hints:[/bold cyan]")
    console.print(Panel(entry.get_task() or "[dim]Empty[/dim]", border_style="green"))

    if show_patch:
        console.print("\n[bold cyan]Patch:[/bold cyan]")
        console.print(Panel(entry.patch or "[dim]Empty[/dim]", border_style="magenta"))

    # Display category-specific fields
    if isinstance(entry, _BugFixTestGenBase):
        bugfix_entry = entry
        if show_patch:
            console.print("\n[bold cyan]Test Patch:[/bold cyan]")
            console.print(Panel(bugfix_entry.test_patch or "[dim]Empty[/dim]", border_style="magenta"))

        console.print("\n[bold cyan]FAIL_TO_PASS Tests:[/bold cyan]")
        if bugfix_entry.fail_to_pass:
            test_table = Table()
            test_table.add_column("Codeunit ID", style="magenta")
            test_table.add_column("Functions", style="yellow")
            for test in bugfix_entry.fail_to_pass:
                test_table.add_row(str(test.codeunitID), ", ".join(test.functionName))
            console.print(test_table)
        else:
            console.print("[dim]No FAIL_TO_PASS tests[/dim]")

        console.print("\n[bold cyan]PASS_TO_PASS Tests:[/bold cyan]")
        if bugfix_entry.pass_to_pass:
            test_table = Table()
            test_table.add_column("Codeunit ID", style="magenta")
            test_table.add_column("Functions", style="yellow")
            for test in bugfix_entry.pass_to_pass:
                test_table.add_row(str(test.codeunitID), ", ".join(test.functionName))
            console.print(test_table)
        else:
            console.print("[dim]No PASS_TO_PASS tests[/dim]")

    elif isinstance(entry, CodeReviewEntry):
        console.print("\n[bold cyan]Expected Review Comments:[/bold cyan]")
        if entry.expected_comments:
            comment_table = Table()
            comment_table.add_column("File", style="magenta")
            comment_table.add_column("Lines", style="yellow")
            comment_table.add_column("Severity", style="red")
            comment_table.add_column("Comment", style="white")
            for comment in entry.expected_comments:
                lines = str(comment.line_start)
                if comment.line_end and comment.line_end != comment.line_start:
                    lines += f"-{comment.line_end}"
                comment_table.add_row(comment.file, lines, comment.severity_label, comment.body)
            console.print(comment_table)
        else:
            console.print("[dim]No expected comments[/dim]")
    elif isinstance(entry, NL2ALEntry):
        console.print("\n[bold cyan]Expected Checklist:[/bold cyan]")
        if entry.expected:
            checklist_table = Table()
            checklist_table.add_column("Level", style="magenta")
            checklist_table.add_column("Assertion", style="yellow")
            for assertion in entry.expected:
                checklist_table.add_row(assertion["level"], assertion["text"])
            console.print(checklist_table)
        else:
            console.print("[dim]No expected assertions[/dim]")


@dataset_app.command("version")
def version(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to resolve the BC version for")],
    category: EvaluationCategoryOption,
    github_output: Annotated[str | None, typer.Option(help="Write the version to GITHUB_OUTPUT with this key name")] = None,
) -> None:
    """Print an entry's environment_setup_version (the BC sandbox version)."""
    entry = category.entry_class.load(category.dataset_path, entry_id=entry_id)[0]
    print(entry.environment_setup_version)
    if github_output:
        write_step_outputs({github_output: entry.environment_setup_version})


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
