from collections.abc import Mapping
from pathlib import Path
from shutil import copytree, rmtree

from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.dataset.dataset_entry import RepoGroundedEntry
from bcbench.logger import get_logger
from bcbench.types import AgentHarness

logger = get_logger(__name__)


def setup_instructions_from_config(
    agent_config: Mapping,
    entry: BaseDatasetEntry,
    repo_path: Path,
    harness: AgentHarness,
    *,
    instructions_root: Path,
    instruction_source_naming: str,
) -> bool:
    """
    Setup custom instructions from config if enabled.

    Args:
        agent_config: Agent configuration dictionary
        entry: Dataset entry naming the customization profile to apply
        repo_path: Path to repository where instructions will be copied
        harness: Agent harness (Copilot or Claude)

    Returns:
        True if instructions are enabled, False otherwise
    """
    instructions_config: dict = agent_config["instructions"]
    instructions_enabled: bool = instructions_config["enabled"]

    if instructions_enabled:
        source_instructions: Path = get_source_instructions_path(entry.customization_profile, instructions_root)
        target_dir: Path = harness.get_target_dir(repo_path)

        logger.info(f"Setting up custom instructions for profile: {entry.customization_profile}")
        if target_dir.exists():
            rmtree(target_dir)
        copytree(source_instructions, target_dir)

        # Rename canonical instruction file to agent-specific name
        canonical = target_dir / instruction_source_naming
        expected = target_dir / harness.instruction_filename
        if canonical.exists() and canonical != expected:
            canonical.rename(expected)
            logger.info(f"Renamed {canonical.name} -> {expected.name}")

        logger.info(f"{target_dir.name} dir is overwritten with {source_instructions}")

    return instructions_enabled


def setup_custom_agent(agent_config: Mapping, entry: BaseDatasetEntry, repo_path: Path, harness: AgentHarness, *, instructions_root: Path) -> str | None:
    """
    Setup custom agents in the repository if available.
    """
    custom_agent_config: dict = agent_config["agents"]
    custom_agent_enabled: bool = custom_agent_config["enabled"]

    if custom_agent_enabled:
        source_instructions: Path = get_source_instructions_path(entry.customization_profile, instructions_root)
        target_dir: Path = harness.get_target_dir(repo_path)
        copytree(source_instructions / "agents", target_dir / "agents", dirs_exist_ok=True)

        logger.info(f"Custom agents are set up from {source_instructions / 'agents'}")
        return custom_agent_config.get("name")

    return None


def get_source_instructions_path(profile: str, instructions_root: Path) -> Path:
    """
    Get path to the source instruction folder for an instruction profile.

    Instructions are stored in shared/instructions/ and used by both Copilot and Claude.

    Raises:
        FileNotFoundError: If instruction file doesn't exist
    """
    instructions_path = instructions_root / profile

    if not instructions_path.exists():
        raise FileNotFoundError(f"Instruction folder not found: {instructions_path}\nExpected for profile: {profile}")

    return instructions_path


def copy_problem_statement_folder(entry: RepoGroundedEntry, repo_path: Path, *, source_dir: Path | None = None, dest_dirname: str | None = None) -> None:
    """
    Copy problem statement folder to the testbed repository root.

    This makes the problem statement (including any screenshots) accessible to Copilot during evaluation.

    Args:
        entry: Dataset entry containing problem_statement path
        repo_path: Path to testbed repository where folder will be copied
    """
    source_dir = source_dir if source_dir is not None else get_config().paths.problem_statement_dir / entry.instance_id
    dest_dir: Path = repo_path / (dest_dirname if dest_dirname is not None else get_config().file_patterns.problem_statement_dest_dir)

    if dest_dir.exists():
        rmtree(dest_dir)

    copytree(source_dir, dest_dir)
    logger.info(f"Copied problem statement folder from {source_dir} to {dest_dir}")
