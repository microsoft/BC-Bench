from pathlib import Path
from shutil import copytree, rmtree

from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.instruction_operations import _get_source_instructions_path
from bcbench.types import AgentType

logger = get_logger(__name__)


def setup_agent_skills(agent_config: dict, entry: DatasetEntry, repo_path: Path, agent_type: AgentType) -> bool:
    """
    Setup skills in the repository if available.

    Returns:
        True if skills were copied, False if skills are disabled.
    """
    skills_enabled: bool = agent_config["skills"]["enabled"]

    if skills_enabled:
        source_skills: Path = _get_source_instructions_path(entry.repo)
        source_skills_dir = source_skills / "skills"

        # Skip if skills folder doesn't exist for this repo
        if not source_skills_dir.exists():
            raise FileNotFoundError(f"Skills folder not found for repository: {entry.repo} at {source_skills_dir}")

        # Copilot reads from .github automatically, Claude reads from .claude automatically
        target_dir: Path = agent_type.get_target_dir(repo_path)
        skills_dir = target_dir / "skills"

        # Remove existing skills directory to ensure clean state
        if skills_dir.exists():
            rmtree(skills_dir)

        copytree(source_skills_dir, skills_dir)

        logger.info(f"Skills copied from {source_skills_dir} to {skills_dir}")
    return skills_enabled
