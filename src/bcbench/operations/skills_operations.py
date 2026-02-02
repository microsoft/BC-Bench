from pathlib import Path
from shutil import copytree

from bcbench.config import get_config
from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.instruction_operations import _get_source_instructions_path

logger = get_logger(__name__)
_config = get_config()


def setup_copilot_skills(copilot_config: dict, entry: DatasetEntry, repo_path: Path) -> list[str] | None:
    """
    Setup skills in the repository if available.

    Returns:
        List of skill directory paths if skills are enabled and exist, None otherwise.
    """
    skills_config: dict = copilot_config["skills"]
    skills_enabled: bool = skills_config["enabled"]

    if skills_enabled:
        source_skills: Path = _get_source_instructions_path(entry.repo)
        source_skills_dir = source_skills / "skills"

        # Skip if skills folder doesn't exist for this repo
        if not source_skills_dir.exists():
            logger.info(f"No skills folder found at {source_skills_dir}, skipping")
            return None

        github_dir: Path = repo_path / ".github"
        skills_dir = github_dir / "skills"
        copytree(source_skills_dir, skills_dir, dirs_exist_ok=True)

        logger.info(f"Skills copied from {source_skills_dir} to {skills_dir}")
        return [str(skills_dir)]

    return None




