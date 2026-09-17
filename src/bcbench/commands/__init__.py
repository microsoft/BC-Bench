"""CLI commands for bcbench."""

from bcbench.commands.bugfix_lifecycle import bugfix_lifecycle_app
from bcbench.commands.category import category_app
from bcbench.commands.dataset import dataset_app
from bcbench.commands.evaluate import evaluate_app
from bcbench.commands.run import run_app

__all__ = ["bugfix_lifecycle_app", "category_app", "dataset_app", "evaluate_app", "run_app"]
