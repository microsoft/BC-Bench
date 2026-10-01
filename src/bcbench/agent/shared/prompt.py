import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from bcbench_core.prompts import render_prompt


def _transform_image_paths(content: str, dest_dir: str) -> str:
    return re.sub(r"!\[([^\]]*)\]\(\./([^)]+)\)", rf"![\1]({dest_dir}/\2)", content)


def build_prompt(
    *,
    template: str,
    task: str,
    repo_path: Path,
    project_paths: Sequence[str],
    problem_statement_dest_dir: str,
    include_project_paths: bool,
    context: Mapping[str, object],
    al_mcp: bool = False,
) -> str:
    return render_prompt(
        template,
        {
            "repo_path": repo_path,
            "task": _transform_image_paths(task, problem_statement_dest_dir),
            "project_paths": ", ".join(project_paths),
            "include_project_paths": include_project_paths,
            "al_mcp": al_mcp,
            **context,
        },
    )
