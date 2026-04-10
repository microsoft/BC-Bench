"""CLI commands for dataset operations."""

import json
from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.cli_options import EvaluationCategoryOption
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry, BugFixEntry
from bcbench.dataset.counterfactual_loader import load_counterfactual_entries
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.exceptions import ConfigurationError
from bcbench.logger import get_logger
from bcbench.types import EvaluationCategory

logger = get_logger(__name__)

dataset_app = typer.Typer(help="Query and analyze dataset")


@dataset_app.command("list")
def list_entries(
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    github_output: Annotated[str | None, typer.Option(help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    modified_only: Annotated[bool, typer.Option(help="Only list entries that have been modified in git diff")] = False,
    base_ref: Annotated[str, typer.Option(help="Git ref to diff against when using --modified-only (e.g., HEAD~1, a commit SHA, or a branch name)")] = "origin/main",
    test_run: Annotated[bool, typer.Option(help="Indicate this is a test run (with 2 entries)")] = False,
    include_counterfactual: Annotated[bool, typer.Option(help="Include counterfactual entries from counterfactual.jsonl")] = True,
    batch: Annotated[int, typer.Option(help="Batch index (1-based) when splitting entries across multiple runs")] = 0,
    batch_count: Annotated[int, typer.Option(help="Total number of batches to split into (0 = no splitting)")] = 0,
):
    """List dataset entry IDs."""
    is_cf = category == EvaluationCategory.COUNTERFACTUAL_EVALUATION

    entry_ids = _list_counterfactual_entries(modified_only, base_ref, test_run) if is_cf else _list_base_entries(category, modified_only, base_ref, test_run, include_counterfactual)

    if batch_count > 0 and batch > 0:
        entry_ids = _select_batch(entry_ids, batch, batch_count)

    print(f"Found {len(entry_ids)} entry(ies){' (modified only)' if modified_only else ''}{f' (batch {batch}/{batch_count})' if batch_count > 0 else ''}:")
    for entry_id in entry_ids:
        print(f"  - {entry_id}")

    if github_output:
        _write_github_output(github_output, json.dumps(entry_ids))


def _list_counterfactual_entries(modified_only: bool, base_ref: str, test_run: bool) -> list[str]:
    from bcbench.config import get_config

    config = get_config()
    cf_path = config.paths.counterfactual_dataset_path
    base_path = config.paths.dataset_dir / "bcbench.jsonl"

    if modified_only:
        import subprocess

        diff_cmd = ["git", "diff", base_ref, "HEAD", "--unified=0", "--no-color", "--diff-filter=AM"]
        result = subprocess.run(
            [*diff_cmd, "--", str(cf_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            cwd=cf_path.parent,
        )
        return _modified_instance_ids_from_diff(result.stdout)

    cf_pairs = load_counterfactual_entries(cf_path, base_path)
    entry_ids = [cf_entry.instance_id for cf_entry, _ in cf_pairs]

    if test_run:
        return entry_ids[:2]
    return entry_ids


def _list_base_entries(category, modified_only: bool, base_ref: str, test_run: bool, include_counterfactual: bool) -> list[str]:
    entry_cls = category.entry_class
    resolved_path = category.dataset_path

    if modified_only:
        import subprocess

        diff_cmd = ["git", "diff", base_ref, "HEAD", "--unified=0", "--no-color", "--diff-filter=AM"]
        result = subprocess.run(
            [*diff_cmd, "--", str(resolved_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            cwd=resolved_path.parent,
        )
        entry_ids: list[str] = _modified_instance_ids_from_diff(result.stdout)

        if include_counterfactual:
            cf_path = resolved_path.parent / "counterfactual.jsonl"
            if cf_path.exists():
                cf_diff_result = subprocess.run(
                    [*diff_cmd, "--", str(cf_path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=True,
                    cwd=cf_path.parent,
                )
                entry_ids.extend(_modified_instance_ids_from_diff(cf_diff_result.stdout))
        return entry_ids

    entries: list[BaseDatasetEntry] = entry_cls.load(resolved_path, random=2 if test_run else None)
    entry_ids = [e.instance_id for e in entries]

    if include_counterfactual:
        cf_path = resolved_path.parent / "counterfactual.jsonl"
        if cf_path.exists():
            cf_pairs = load_counterfactual_entries(cf_path, resolved_path)
            entry_ids.extend(cf_entry.instance_id for cf_entry, _ in cf_pairs)

    return entry_ids


def _select_batch(entry_ids: list[str], batch: int, batch_count: int) -> list[str]:
    total = len(entry_ids)
    chunk_size = (total + batch_count - 1) // batch_count
    start = (batch - 1) * chunk_size
    return entry_ids[start : start + chunk_size]


@dataset_app.command("view")
def view_entry(
    entry_id: Annotated[str, typer.Argument(help="Entry ID to view")],
    category: EvaluationCategoryOption = EvaluationCategory.BUG_FIX,
    show_patch: Annotated[bool, typer.Option(help="Show patch in output")] = False,
):
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


@dataset_app.command("cf-extract")
def cf_extract(
    entry_id: Annotated[str, typer.Argument(help="Base entry ID to extract workspace from")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o", help="Directory to create workspace in")] = Path("cf-workspace"),
    repo_path: Annotated[Path | None, typer.Option("--repo-path", "-r", help="Repository path for full-fidelity extraction")] = None,
):
    """Extract patch hunks into an editable workspace for counterfactual authoring."""
    from bcbench.dataset.cf_workspace import extract_workspace

    entry = BugFixEntry.load(EvaluationCategory.BUG_FIX.dataset_path, entry_id=entry_id)[0]

    workspace = extract_workspace(entry, output_dir, repo_path)

    typer.echo(f"Workspace created at: {workspace}")
    typer.echo("  fix/after/   — edit these files to change the fix")
    typer.echo("  test/after/  — edit these files to change the tests")
    typer.echo(f"Run 'bcbench dataset cf-create {workspace}' when done editing.")


@dataset_app.command("cf-create")
def cf_create(
    workspace_dir: Annotated[Path, typer.Argument(help="Path to the workspace directory")],
    variant_description: Annotated[str, typer.Option("--variant-description", "-d", help="Description of the counterfactual variant")],
):
    """Create a counterfactual entry from an edited workspace."""
    from bcbench.dataset.cf_workspace import create_cf_entry

    cf_entry = create_cf_entry(workspace_dir, variant_description)

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
