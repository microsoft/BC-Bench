"""CLI commands for bcbench."""

from bcbench.commands.category import category_app
from bcbench.commands.dataset import dataset_app
from bcbench.commands.evaluate import evaluate_app
from bcbench.commands.redteam import redteam_app
from bcbench.commands.run import run_app

__all__ = ["category_app", "dataset_app", "evaluate_app", "redteam_app", "run_app"]
