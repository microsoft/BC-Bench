"""CLI entry point for bcbench using typer."""

import typer
from dotenv import load_dotenv
from typing_extensions import Annotated

from bcbench.commands import dataset_app, evaluate_app, run_app
from bcbench.commands.collect import collect_app
from bcbench.config import get_config
from bcbench.logger import setup_logger

load_dotenv()
get_config()

app = typer.Typer(
    name="bcbench",
    help="BC-Bench: Benchmarking tool for Business Central (AL) ecosystem",
    no_args_is_help=True,
    add_completion=True,
)

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


if __name__ == "__main__":
    app()
