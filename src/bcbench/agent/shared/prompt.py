import re
from pathlib import Path

from jinja2 import Template

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.types import EvaluationCategory

_config = get_config()


def _transform_image_paths(content: str) -> str:
    dest_dir = _config.file_patterns.problem_statement_dest_dir
    return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)


def build_prompt(entry: BaseDatasetEntry, repo_path: Path, config: dict, category: EvaluationCategory, al_mcp: bool = False) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get(f"{category.prompt_template_key}-template")
    include_project_paths = prompt_config.get("include_project_paths")

    test_gen_input: str = prompt_config.get("test-generation-input", "problem-statement")
    is_gold_patch: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("gold-patch", "both")
    is_problem_statement: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("problem-statement", "both")

    task = _transform_image_paths(entry.get_task())

    template = Template(template_str)
    return template.render(
        repo_path=repo_path,
        task=task,
        project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
        is_gold_patch=is_gold_patch,  # only relevant for test-generation
        is_problem_statement=is_problem_statement,  # only relevant for test-generation
        al_mcp=al_mcp,  # whether AL MCP server is enabled
    )
