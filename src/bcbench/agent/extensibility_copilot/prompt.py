from pathlib import Path

from jinja2 import Template

from bcbench.dataset import DatasetEntryV2


def build_prompt(entry: DatasetEntryV2, repo_path: Path, config: dict) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get("template")
    include_project_paths = prompt_config.get("include_project_paths")

    template = Template(template_str)
    return template.render(
        repo_path=repo_path,
        task=entry.get_task(),
        #project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
    )
