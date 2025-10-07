"""CLI entry point for bcbench using typer."""

from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from bcbench.core.logger import setup_logger
from bcbench.core.utils import DATASET_PATH, NAV_REPO_PATH

app = typer.Typer(
    name="bcbench",
    help="BC-Bench: Benchmarking tool for Business Central (AL) ecosystem",
    no_args_is_help=True,
    add_completion=False,
)

# Create sub-apps for command groups
collect_app = typer.Typer(help="Collect dataset entries from various sources")
agent_app = typer.Typer(help="Run AI agents on benchmark tasks")
validate_app = typer.Typer(help="Validate dataset entries")
dataset_app = typer.Typer(help="Query and analyze dataset")

app.add_typer(collect_app, name="collect")
app.add_typer(agent_app, name="agent")
app.add_typer(validate_app, name="validate")
app.add_typer(dataset_app, name="dataset")


@app.command("version")
def show_version():
    """Show bcbench version."""
    from importlib.metadata import version

    print(f"bcbench version {version('bcbench')}")


@collect_app.command("nav")
def collect_nav(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    output: Annotated[Path, typer.Option(help="Output file path")] = DATASET_PATH,
    append: Annotated[bool, typer.Option(help="Append to output file instead of overwriting")] = False,
    skip_validate: Annotated[bool, typer.Option(help="Skip schema validation before writing")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """
    Collect dataset entry from Azure DevOps NAV pull request.

    Try it out with: bcbench collect nav 210528 --output dataset/bcbench_nav.jsonl --append --skip-validate
    """
    setup_logger(verbose)
    from bcbench.collection.collect_nav import collect_nav_entry

    collect_nav_entry(
        pr_number=pr_number,
        output=output,
        append=append,
        skip_validate=skip_validate,
    )


@validate_app.command("dataset")
def validate_dataset(
    dataset_path: Annotated[Path, typer.Argument(help="Path to dataset file")] = DATASET_PATH,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """Validate all entries in the dataset against the JSON schema."""
    setup_logger(verbose)
    from bcbench.validation.validate_schema import validate_dataset_file

    validate_dataset_file(dataset_path)


@agent_app.command("mini")
def mini_bc_agent(
    instance_id: Annotated[str, typer.Argument(help="Instance ID from the dataset")],
    repo_path: Annotated[Path, typer.Option(help="Path to NAV repository")] = NAV_REPO_PATH,
    use_container: Annotated[bool, typer.Option(help="Use containerized BC environment")] = False,
    container_name: Annotated[Optional[str], typer.Option(help="BC container name (required if --use-container)")] = None,
    username: Annotated[str, typer.Option(help="Username for BC container")] = "admin",
    password: Annotated[Optional[str], typer.Option(help="Password for BC container (or set BC_CONTAINER_PASSWORD env var)")] = None,
    step_limit: Annotated[int, typer.Option(help="Maximum number of agent steps")] = 20,
    cost_limit: Annotated[float, typer.Option(help="Maximum cost limit for agent")] = 1.0,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """
    Run the AI agent on a dataset entry.

    Try it out with: bcbench agent mini microsoftInternal__NAV-210528
    """
    setup_logger(verbose)
    from bcbench.agent.mini_agent import run_agent

    run_agent(
        instance_id=instance_id,
        repo_path=repo_path,
        use_container=use_container,
        container_name=container_name,
        username=username,
        password=password,
        step_limit=step_limit,
        cost_limit=cost_limit,
    )


@dataset_app.command("versions")
def list_versions(
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    github_output: Annotated[Optional[str], typer.Option("--github-output", help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """
    Get unique environment_setup_version values from the dataset.

    By default, displays versions in a human-readable format. Use --github-output <key>
    to write JSON output to GITHUB_OUTPUT for use in CI/CD workflows.
    """
    setup_logger(verbose)
    from bcbench.core.dataset_queries import query_versions

    query_versions(dataset_path, github_output)


@dataset_app.command("entries")
def list_entries(
    version: Annotated[str, typer.Argument(help="Environment setup version to filter by")],
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    github_output: Annotated[Optional[str], typer.Option("--github-output", help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """
    Get all instance IDs for a specific environment_setup_version.

    By default, displays entries in a human-readable format. Use --github-output <key>
    to write JSON output to GITHUB_OUTPUT for use in CI/CD workflows.
    """
    setup_logger(verbose)
    from bcbench.core.dataset_queries import query_entries

    query_entries(version, dataset_path, github_output)


@dataset_app.command("entry-matrix")
def list_entry_matrix(
    dataset_path: Annotated[Path, typer.Option(help="Path to dataset file")] = DATASET_PATH,
    github_output: Annotated[Optional[str], typer.Option("--github-output", help="Write JSON output to GITHUB_OUTPUT with this key name")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """
    Get all entries with version info for GitHub Actions matrix strategy.

    Returns a list of objects with 'entry' and 'version' keys, suitable for use
    with GitHub Actions matrix.include strategy. Use --github-output <key> to
    write JSON output to GITHUB_OUTPUT for use in CI/CD workflows.
    """
    setup_logger(verbose)
    from bcbench.core.dataset_queries import query_entry_matrix

    query_entry_matrix(dataset_path, github_output)


if __name__ == "__main__":
    app()
