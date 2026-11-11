import sys

import typer

from bcbench.cli_options import EvaluationCategoryOption
from bcbench.github_actions import write_step_outputs
from bcbench.types import EvaluationCategory

category_app = typer.Typer(help="Category-specific configuration helpers")


@category_app.command("list")
def list_categories() -> None:
    """Print all evaluation category names, one per line."""
    for category in EvaluationCategory:
        sys.stdout.write(f"{category.value}\n")


@category_app.command("bceval-config")
def bceval_config(category: EvaluationCategoryOption) -> None:
    """
    Emit the bc-eval evaluator list and core score for a category as step outputs.

    The lines are appended to $GITHUB_OUTPUT so they become GitHub Actions step outputs. Outside of Actions nothing is written.
    """
    outputs: dict[str, str] = {
        "evaluators": ",".join(category.evaluators),
        "core_score": category.core_score,
    }
    if ("lm_checklist" in category.evaluators) and (category.judge_model is not None):
        outputs["judge_model"] = category.judge_model
    write_step_outputs(outputs)


@category_app.command("runtime-config")
def runtime_config(category: EvaluationCategoryOption) -> None:
    """Emit the GitHub Actions runner label and environment requirements for a category."""
    write_step_outputs(
        {
            "runner": category.runner,
            "requires-container": str(category.requires_container).lower(),
            "requires-repo": str(category.requires_repo).lower(),
        }
    )
