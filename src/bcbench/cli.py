"""CLI entry point for bcbench using typer."""

from pathlib import Path

import typer
from typing_extensions import Annotated

from bcbench.core.logger import setup_logger
from bcbench.core.utils import DATASET_PATH
from bcbench.agent import run_app
from bcbench.dataset import dataset_app
from bcbench.evaluate import evaluate_app

app = typer.Typer(
    name="bcbench",
    help="BC-Bench: Benchmarking tool for Business Central (AL) ecosystem",
    no_args_is_help=True,
    add_completion=False,
)

collect_app = typer.Typer(help="Collect dataset entries from various sources")

app.add_typer(collect_app, name="collect")
app.add_typer(run_app, name="run")
app.add_typer(dataset_app, name="dataset")
app.add_typer(evaluate_app, name="evaluate")


@app.callback()
def logging_callback(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """Setup logging for all commands."""
    setup_logger(verbose)


@app.command("version")
def show_version():
    """Show bcbench version."""
    from importlib.metadata import version

    print(f"bcbench version {version('bcbench')}")


@collect_app.command("nav")
def collect_nav(
    pr_number: Annotated[int, typer.Argument(help="Pull request number to collect")],
    output: Annotated[Path, typer.Option(help="Output file path")] = DATASET_PATH,
    overwrite: Annotated[bool, typer.Option(help="Overwrite output file instead of appending")] = False,
    diff_path: Annotated[str, typer.Option(help="Filter git diff to only show changes under this path")] = "",
):
    """
    Collect dataset entry from Azure DevOps NAV pull request.

    Try it out with: bcbench collect nav 210528 --output dataset/bcbench_nav.jsonl

    For BaseApp Data, use diff_path: .\\App\\Layers\\W1\\:
    """
    from bcbench.collection.collect_nav import collect_nav_entry

    collect_nav_entry(
        pr_number=pr_number,
        output=output,
        overwrite=overwrite,
        diff_path=diff_path,
    )


if __name__ == "__main__":
    app()
