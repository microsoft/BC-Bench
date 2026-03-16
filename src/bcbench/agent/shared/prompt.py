from pathlib import Path

from jinja2 import Template

from bcbench.dataset import BaseDatasetEntry
from bcbench.types import EvaluationCategory


def build_prompt(entry: BaseDatasetEntry, repo_path: Path, config: dict, category: EvaluationCategory, al_mcp: bool = False) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get(f"{category.value}-template")
    include_project_paths = prompt_config.get("include_project_paths")

    test_gen_input: str = prompt_config.get("test-generation-input", "problem-statement")
    is_gold_patch: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("gold-patch", "both")
    is_problem_statement: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("problem-statement", "both")

    template = Template(template_str)
    return template.render(
        repo_path=repo_path,
        task=entry.get_task(transform_image_paths=True),
        project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
        is_gold_patch=is_gold_patch,  # only relevant for test-generation
        is_problem_statement=is_problem_statement,  # only relevant for test-generation
        al_mcp=al_mcp,  # whether AL MCP server is enabled
    )
