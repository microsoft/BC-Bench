import re
from pathlib import Path

from jinja2.sandbox import SandboxedEnvironment

from bcbench.dataset import BaseDatasetEntry, RepoGroundedEntry
from bcbench.types import AgentConfig, EvaluationCategory, TestGenerationInput

_jinja = SandboxedEnvironment(autoescape=False)


def _transform_image_paths(content: str) -> str:
    dest_dir = RepoGroundedEntry.WORKSPACE_PROBLEM_DIR
    return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)


def build_prompt(entry: BaseDatasetEntry, repo_path: Path, config: AgentConfig, category: EvaluationCategory, al_mcp: bool = False) -> str:
    prompt_config = config.prompt
    template_str = prompt_config.templates[category]

    test_gen_input: TestGenerationInput = prompt_config.test_generation_input
    is_gold_patch: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("gold-patch", "both")
    is_problem_statement: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("problem-statement", "both")

    task = _transform_image_paths(entry.get_task())

    return _jinja.from_string(template_str).render(
        repo_path=repo_path,
        task=task,
        project_paths=", ".join(entry.project_paths),
        include_project_paths=prompt_config.include_project_paths,
        is_gold_patch=is_gold_patch,  # only relevant for test-generation
        is_problem_statement=is_problem_statement,  # only relevant for test-generation
        al_mcp=al_mcp,  # whether AL MCP server is enabled
    )
