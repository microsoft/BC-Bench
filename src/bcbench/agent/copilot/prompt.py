from pathlib import Path

from jinja2 import Template

from bcbench.dataset import DatasetEntry
from bcbench.types import EvaluationCategory


def build_prompt(entry: DatasetEntry, repo_path: Path, config: dict, category: EvaluationCategory) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get(f"{category.value}-template")
    include_project_paths = prompt_config.get("include_project_paths")

    template = Template(template_str)
    return template.render(
        repo_path=repo_path,
        task=entry.get_task(transform_image_paths=True),
        project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
    )
