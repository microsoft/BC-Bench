"""CLI commands for bcbench."""

from bcbench.commands.dataset import dataset_app
from bcbench.commands.evaluate import evaluate_app
from bcbench.commands.run import run_app

__all__ = ["dataset_app", "evaluate_app", "run_app"]
