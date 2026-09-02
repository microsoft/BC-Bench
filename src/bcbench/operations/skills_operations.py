from pathlib import Path
from shutil import copytree, rmtree

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.logger import get_logger
from bcbench.operations.instruction_operations import _get_source_instructions_path
from bcbench.types import AgentHarness

logger = get_logger(__name__)


def _select_skills(source_skills_dir: Path, names: list[str]) -> list[Path]:
    """Skill folders to copy: the ones named in ``skills.names``, or all of them when unnamed.

    A profile that holds none of the named skills contributes no skills, rather than failing the run:
    ``skills.names`` is one global list, but profiles are per dataset entry, so a name that is missing
    here is normal for a category the arm does not target. The result records what was actually
    copied, so a run that ends up without skills is visible rather than silent.
    """
    available: list[Path] = sorted(path for path in source_skills_dir.iterdir() if path.is_dir())

    if not names:
        return available

    selected: list[Path] = [path for path in available if path.name in names]
    skipped: list[str] = [name for name in names if name not in {path.name for path in selected}]

    if skipped:
        logger.warning(f"Configured skills not present in {source_skills_dir}, skipping: {skipped} (available: {[path.name for path in available]})")

    return selected


def setup_agent_skills(
    agent_config: dict,
    entry: BaseDatasetEntry,
    repo_path: Path,
    harness: AgentHarness,
) -> list[str]:
    """Copy skills into the repository when enabled via ``config.yaml``'s ``skills.enabled``.

    Returns:
        Names of the skills copied into the repository; empty when skills are disabled.
    """
    skills_enabled: bool = agent_config["skills"]["enabled"]

    if not skills_enabled:
        return []

    source_skills: Path = _get_source_instructions_path(entry.customization_profile)
    source_skills_dir = source_skills / "skills"

    if not source_skills_dir.exists():
        raise FileNotFoundError(f"Skills folder not found for profile: {entry.customization_profile} at {source_skills_dir}")

    selected_skills: list[Path] = _select_skills(source_skills_dir, agent_config["skills"].get("names") or [])

    # Copilot reads from .github automatically, Claude reads from .claude automatically
    target_dir: Path = harness.get_target_dir(repo_path)
    skills_dir = target_dir / "skills"

    # Remove existing skills directory to ensure clean state
    if skills_dir.exists():
        rmtree(skills_dir)

    if not selected_skills:
        return []

    skills_dir.mkdir(parents=True)
    for skill in selected_skills:
        copytree(skill, skills_dir / skill.name)

    copied_names: list[str] = [skill.name for skill in selected_skills]
    logger.info(f"Skills copied from {source_skills_dir} to {skills_dir}: {copied_names}")
    return copied_names
