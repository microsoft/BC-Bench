import re
from pathlib import Path

from bcbench_core.prompts import render_prompt

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.types import EvaluationCategory

_config = get_config()


def _transform_image_paths(content: str) -> str:
    dest_dir = _config.file_patterns.problem_statement_dest_dir
    return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)


def build_prompt(entry: BaseDatasetEntry, repo_path: Path, config: dict, category: EvaluationCategory, al_mcp: bool = False) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get(f"{category.value}-template")
    include_project_paths = prompt_config.get("include_project_paths")

    task = _transform_image_paths(entry.get_task())

    return render_prompt(
        template_str,
        {
            "repo_path": repo_path,
            "task": task,
            "project_paths": ", ".join(entry.project_paths),
            "include_project_paths": include_project_paths,
            "al_mcp": al_mcp,
            **category.definition.prompt_context(prompt_config),
        },
    )
