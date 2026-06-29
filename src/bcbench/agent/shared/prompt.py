import re
from pathlib import Path

from jinja2 import Template

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.types import AgentType, EvaluationCategory

_config = get_config()


def _transform_image_paths(content: str) -> str:
    dest_dir = _config.file_patterns.problem_statement_dest_dir
    return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)


def build_prompt(entry: BaseDatasetEntry, repo_path: Path, config: dict, category: EvaluationCategory, agent_type: AgentType, al_mcp: bool = False) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get(f"{category.value}-template")

    context = {
        "repo_path": repo_path,
        "task": _transform_image_paths(entry.get_task()),
        "project_paths": ", ".join(entry.project_paths),
        "include_project_paths": prompt_config.get("include_project_paths"),
        "al_mcp": al_mcp,
    }
    context |= _category_context(category, config, agent_type, repo_path)

    return Template(template_str).render(**context)


def _category_context(category: EvaluationCategory, config: dict, agent_type: AgentType, repo_path: Path) -> dict:
    match category:
        case EvaluationCategory.TEST_GENERATION:
            mode = config.get("prompt", {}).get("test-generation-input", "problem-statement")
            return {
                "is_gold_patch": mode in ("gold-patch", "both"),
                "is_problem_statement": mode in ("problem-statement", "both"),
            }
        case EvaluationCategory.CODE_REVIEW:
            return {
                "inline_instructions_enabled": config.get("instructions", {}).get("enabled", False),
                "instructions_dir": f"{agent_type.get_target_dir(repo_path).name}/instructions",
            }
        case _:
            return {}
