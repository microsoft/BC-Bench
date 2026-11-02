import logging
from pathlib import Path
from shutil import copytree, rmtree

from bcbench.operations.instruction_operations import require_dir
from bcbench.types import ToggleConfig

logger = logging.getLogger(__name__)


def setup_agent_skills(config: ToggleConfig, source_dir: Path, target_dir: Path) -> bool:
    """Replace ``target_dir/skills`` with a copy of ``source_dir/skills`` when enabled.

    Returns:
        Whether skills are enabled.
    """
    if not config.enabled:
        return False

    source_skills = source_dir / "skills"
    require_dir(source_skills)
    skills_dir = target_dir / "skills"
    if skills_dir.exists():
        rmtree(skills_dir)
    copytree(source_skills, skills_dir)

    logger.info(f"Skills copied from {source_skills} to {skills_dir}")
    return True
