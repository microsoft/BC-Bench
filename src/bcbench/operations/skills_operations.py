from pathlib import Path
from shutil import copytree

from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.instruction_operations import _get_source_instructions_path

logger = get_logger(__name__)

def setup_copilot_skills(copilot_config: dict, entry: DatasetEntry, repo_path: Path) -> bool:
    """
    Setup skills in the repository if available.

    Returns:
        True if skills were copied, False if skills are disabled.
    """
    skills_enabled: bool = copilot_config["skills"]["enabled"]

    if skills_enabled:
        source_skills: Path = _get_source_instructions_path(entry.repo)
        source_skills_dir = source_skills / "skills"

        # Skip if skills folder doesn't exist for this repo
        if not source_skills_dir.exists():
            raise FileNotFoundError(f"Skills folder not found for repository: {entry.repo} at {source_skills_dir}")

        github_dir: Path = repo_path / ".github"
        skills_dir = github_dir / "skills"
        copytree(source_skills_dir, skills_dir, dirs_exist_ok=True)

        logger.info(f"Skills copied from {source_skills_dir} to {skills_dir}")
        return True

    return False



