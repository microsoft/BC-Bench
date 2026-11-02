import logging
from pathlib import Path
from shutil import copytree, rmtree

from bcbench.dataset.dataset_entry import WORKSPACE_PROBLEM_DIR, RepoGroundedEntry
from bcbench.paths import AGENT_SHARE_DIR
from bcbench.types import CustomAgentsConfig, ToggleConfig

logger = logging.getLogger(__name__)

INSTRUCTION_SOURCE_FILE = "AGENTS.md"


def instructions_profile_dir(profile: str) -> Path:
    """Shipped instructions, skills and custom agents for a customization profile, shared by Copilot and Claude."""
    return AGENT_SHARE_DIR / "instructions" / profile


def setup_instructions_from_config(config: ToggleConfig, source_dir: Path, target_dir: Path, instruction_filename: str) -> bool:
    """Replace ``target_dir`` with a copy of ``source_dir`` when enabled.

    The canonical ``AGENTS.md`` is renamed to ``instruction_filename``, the file the agent reads.

    Returns:
        Whether instructions are enabled.
    """
    if not config.enabled:
        return False

    require_dir(source_dir)
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


def setup_custom_agent(config: CustomAgentsConfig, source_dir: Path, target_dir: Path) -> str | None:
    """Copy ``source_dir/agents`` into ``target_dir/agents`` when enabled.

    Returns:
        The custom agent to run, or None when custom agents are disabled.
    """
    if not config.enabled:
        return None

    source_agents = source_dir / "agents"
    require_dir(source_agents)
    copytree(source_agents, target_dir / "agents", dirs_exist_ok=True)

    logger.info(f"Custom agents are set up from {source_agents}")
    return config.name


def require_dir(path: Path) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"Folder not found: {path}")


def copy_problem_statement_folder(entry: RepoGroundedEntry, repo_path: Path) -> None:
    """
    Copy problem statement folder to the testbed repository root.

    This makes the problem statement (including any screenshots) accessible to Copilot during evaluation.

    Args:
        entry: Dataset entry containing problem_statement path
        repo_path: Path to testbed repository where folder will be copied
    """
    source_dir: Path = entry.problem_statement_dir
    dest_dir: Path = repo_path / WORKSPACE_PROBLEM_DIR

    if dest_dir.exists():
        rmtree(dest_dir)

    copytree(source_dir, dest_dir)
    logger.info(f"Copied problem statement folder from {source_dir} to {dest_dir}")
