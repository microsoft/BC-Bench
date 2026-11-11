"""Customize the agent under test by copying instructions, skills and custom agents into its workspace."""

import logging
from pathlib import Path
from shutil import copytree, rmtree

from pydantic import BaseModel, ConfigDict, StrictBool

logger = logging.getLogger(__name__)

__all__ = ["INSTRUCTION_SOURCE_FILE", "CustomAgentsConfig", "ToggleConfig", "setup_custom_agent", "setup_instructions", "setup_skills"]

# Harness-neutral instruction file name; renamed to the file the agent reads (e.g. copilot-instructions.md, CLAUDE.md)
INSTRUCTION_SOURCE_FILE = "AGENTS.md"


class ToggleConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: StrictBool = False


class CustomAgentsConfig(ToggleConfig):
    name: str | None = None


def setup_instructions(config: ToggleConfig, source_dir: Path, target_dir: Path, instruction_filename: str) -> bool:
    """Replace ``target_dir`` with a copy of ``source_dir`` when enabled.

    ``AGENTS.md`` is renamed to ``instruction_filename``, the file the agent reads.

    Returns:
        Whether instructions are enabled.
    """
    if not config.enabled:
        return False

    _require_dir(source_dir)
    if target_dir.exists():
        rmtree(target_dir)
    copytree(source_dir, target_dir)

    canonical = target_dir / INSTRUCTION_SOURCE_FILE
    expected = target_dir / instruction_filename
    if canonical.exists() and canonical != expected:
        canonical.rename(expected)
        logger.info(f"Renamed {canonical.name} -> {expected.name}")

    logger.info(f"{target_dir} is overwritten with {source_dir}")
    return True


def setup_skills(config: ToggleConfig, source_dir: Path, target_dir: Path) -> bool:
    """Replace ``target_dir/skills`` with a copy of ``source_dir/skills`` when enabled.

    Returns:
        Whether skills are enabled.
    """
    if not config.enabled:
        return False

    source_skills = source_dir / "skills"
    _require_dir(source_skills)
    skills_dir = target_dir / "skills"
    if skills_dir.exists():
        rmtree(skills_dir)
    copytree(source_skills, skills_dir)

    logger.info(f"Skills copied from {source_skills} to {skills_dir}")
    return True


def setup_custom_agent(config: CustomAgentsConfig, source_dir: Path, target_dir: Path) -> str | None:
    """Copy ``source_dir/agents`` into ``target_dir/agents`` when enabled.

    Returns:
        The custom agent to run, or None when custom agents are disabled.
    """
    if not config.enabled:
        return None

    source_agents = source_dir / "agents"
    _require_dir(source_agents)
    copytree(source_agents, target_dir / "agents", dirs_exist_ok=True)

    logger.info(f"Custom agents are set up from {source_agents}")
    return config.name


def _require_dir(path: Path) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"Folder not found: {path}")
