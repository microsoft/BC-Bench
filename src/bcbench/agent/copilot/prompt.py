from pathlib import Path

from jinja2 import Template

from bcbench.dataset import DatasetEntry, PRDatasetEntry


def build_prompt(entry: DatasetEntry, repo_path: Path, config: dict) -> str:
    prompt_config = config.get("prompt", {})
    template_str = prompt_config.get("template")
    include_project_paths = prompt_config.get("include_project_paths")

    template = Template(template_str)
    return template.render(
        repo_path=repo_path,
        task=entry.get_task(),
        project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
    )


def build_pr_review_prompt(
    entry: PRDatasetEntry,
    instructions_template: str,
) -> str:
    """Build a prompt for PR security review task.

    Replaces placeholders in the instructions template with PR dataset values.
    Uses simple string replacement instead of .format() to avoid conflicts with
    curly braces in code examples.

    Args:
        entry: PR dataset entry containing PR metadata
        instructions_template: Template string with placeholders {prname}, {prdescription}, {diff}

    Returns:
        Complete prompt with placeholders replaced
    """
    prompt = instructions_template
    # Use simple string replacement to avoid issues with curly braces in code examples
    prompt = prompt.replace("{prname}", entry.name)
    prompt = prompt.replace("{prdescription}", entry.description)
    prompt = prompt.replace("{diff}", entry.diff)
    return prompt
