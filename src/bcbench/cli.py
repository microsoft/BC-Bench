"""CLI entry point for bcbench using typer."""

import io
import sys
from importlib.util import find_spec
from typing import Annotated

import typer

from bcbench.commands import dataset_app, evaluate_app, run_app
from bcbench.commands.category import category_app
from bcbench.commands.collect import collect_app
from bcbench.commands.contamination import contamination_app
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
app.add_typer(category_app, name="category")
app.add_typer(contamination_app, name="contamination")


def _redteam_group_installed() -> bool:
    # find_spec raises (rather than returning None) when a parent package is missing entirely.
    try:
        return find_spec("azure.ai.evaluation") is not None
    except ModuleNotFoundError:
        return False


def _add_redteam_app() -> None:
    """Register `bcbench redteam`, whose azure-ai-evaluation[redteam] tree ships as an optional dependency group.

    Importing `bcbench.commands.redteam` pulls that tree in, so probe for it first and otherwise
    register a catch-all that names the missing group instead of an opaque "no such command".
    """
    if not _redteam_group_installed():

        @app.command("redteam", context_settings={"ignore_unknown_options": True}, help="Red team BC-Bench agents (needs `uv sync --group redteam`)")
        def _missing_group(args: Annotated[list[str] | None, typer.Argument(hidden=True)] = None) -> None:
            raise typer.BadParameter("`bcbench redteam` needs the optional redteam dependency group. Install it with `uv sync --group redteam`.")

        return

    from bcbench.commands.redteam import redteam_app

    app.add_typer(redteam_app, name="redteam")


_add_redteam_app()


@app.callback()
def logging_callback(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable debug logging")] = False,
) -> None:
    """Setup logging for all commands."""
    setup_logger(verbose)


if __name__ == "__main__":
    app()
