"""CLI entry point for bcbench using typer."""

import io
import sys

import typer
from typing_extensions import Annotated

from bcbench.commands import dataset_app, evaluate_app, run_app
from bcbench.commands.collect import collect_app
from bcbench.commands.result import result_app
from bcbench.config import get_config
from bcbench.logger import setup_logger

get_config()

# Ensure UTF-8 encoding for stdout/stderr on Windows GitHub Action runner (default is cp1252)
if isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout.reconfigure(encoding="utf-8")
if isinstance(sys.stderr, io.TextIOWrapper):
    sys.stderr.reconfigure(encoding="utf-8")

app = typer.Typer(
    name="bcbench",
    help="BC-Bench: Benchmarking tool for Business Central (AL) ecosystem",
    no_args_is_help=True,
    add_completion=True,
    pretty_exceptions_show_locals=False,
)

app.add_typer(collect_app, name="collect")
app.add_typer(run_app, name="run")
app.add_typer(dataset_app, name="dataset")
app.add_typer(evaluate_app, name="evaluate")
app.add_typer(result_app, name="result")


@app.callback()
def logging_callback(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
):
    """Setup logging for all commands."""
    setup_logger(verbose)


if __name__ == "__main__":
    app()
