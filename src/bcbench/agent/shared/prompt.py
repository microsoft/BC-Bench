import re
from pathlib import Path

from jinja2.sandbox import SandboxedEnvironment

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory, HistorySettings

_config = get_config()

_jinja = SandboxedEnvironment(autoescape=False)


def _transform_image_paths(content: str) -> str:
    dest_dir = _config.file_patterns.problem_statement_dest_dir
    return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)


def build_prompt(entry: BaseDatasetEntry, repo_path: Path, config: dict, category: EvaluationCategory, al_mcp: bool = False, history: HistorySettings | None = None) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get(f"{category.value}-template")
    include_project_paths = prompt_config.get("include_project_paths")

    test_gen_input: str = prompt_config.get("test-generation-input", "problem-statement")
    is_gold_patch: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("gold-patch", "both")
    is_problem_statement: bool = category == EvaluationCategory.TEST_GENERATION and test_gen_input in ("problem-statement", "both")

    task = _transform_image_paths(entry.get_task())

    prompt = _jinja.from_string(template_str).render(
        repo_path=repo_path,
        task=task,
        project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
        is_gold_patch=is_gold_patch,  # only relevant for test-generation
        is_problem_statement=is_problem_statement,  # only relevant for test-generation
        al_mcp=al_mcp,  # whether AL MCP server is enabled
    )
    if category.supports_history and history is not None and (history.enabled or history.measure_scope):
        investigation_template = prompt_config.get("investigation-template")
        if not investigation_template:
            raise AgentError("Scope/history measurements require prompt.investigation-template")
        instructions = _jinja.from_string(investigation_template).render(history_enabled=history.enabled)
        return f"{prompt}\n\n{instructions}"
    return prompt
