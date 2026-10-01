import sys
from pathlib import Path

import typer

from bcbench.categories.base import CategoryEvaluator, JudgeCategoryDefinition
from bcbench.cli_options import EvaluationCategoryOption
from bcbench.commands.composition import build_category_registry, command_context
from bcbench.github_actions import write_step_outputs

category_app = typer.Typer(help="Category-specific configuration helpers")


@category_app.command("list")
def list_categories(ctx: typer.Context) -> None:
    """Print registered evaluation category names, one per line."""
    registry = build_category_registry(command_context(ctx))
    for name in registry:
        sys.stdout.write(f"{name}\n")


@category_app.command("bceval-config")
def bceval_config(ctx: typer.Context, category: EvaluationCategoryOption) -> None:
    """Emit the bc-eval evaluator list and core score as step outputs."""
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    outputs = {
        "evaluators": ",".join(definition.reporting.evaluators),
        "core_score": definition.reporting.core_score,
    }
    if CategoryEvaluator.LM_CHECKLIST in definition.reporting.evaluators and isinstance(definition, JudgeCategoryDefinition):
        outputs["judge_model"] = definition.judge_model
    output_path = Path(state.config.env.github_output) if state.config.env.github_output else None
    write_step_outputs(outputs, output_path=output_path)


@category_app.command("runtime-config")
def runtime_config(ctx: typer.Context, category: EvaluationCategoryOption) -> None:
    """Emit the GitHub Actions runner label and environment requirements."""
    state = command_context(ctx)
    definition = build_category_registry(state)[category]
    output_path = Path(state.config.env.github_output) if state.config.env.github_output else None
    write_step_outputs(
        {
            "runner": definition.reporting.runner,
            "requires-container": str(definition.capabilities.requires_container).lower(),
            "requires-repo": str(definition.requires_repo).lower(),
        },
        output_path=output_path,
    )
