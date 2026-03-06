from pathlib import Path
from shutil import copytree, rmtree

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.logger import get_logger
from bcbench.types import AgentType

logger = get_logger(__name__)
_config = get_config()


def setup_instructions_from_config(copilot_config: dict, entry: DatasetEntry, repo_path: Path, agent_type: AgentType) -> bool:
    """
    Setup custom instructions from config if enabled.

    Args:
        copilot_config: Copilot agent configuration dictionary
        entry: Dataset entry containing repo information
        repo_path: Path to repository where instructions will be copied
        agent_type: Type of agent (Copilot or Claude)

    Returns:
        True if instructions are enabled, False otherwise
    """
    instructions_config: dict = copilot_config["instructions"]
    instructions_enabled: bool = instructions_config["enabled"]

    if instructions_enabled:
        source_instructions: Path = _get_source_instructions_path(entry.repo)
        target_dir: Path = agent_type.get_target_dir(repo_path)

        logger.info(f"Setting up custom instructions for repository: {entry.repo}")
        if target_dir.exists():
            rmtree(target_dir)
        copytree(source_instructions, target_dir)

        # Rename canonical instruction file to agent-specific name
        canonical = target_dir / _config.file_patterns.instruction_source_naming
        expected = target_dir / agent_type.instruction_filename
        if canonical.exists() and canonical != expected:
            canonical.rename(expected)
            logger.info(f"Renamed {canonical.name} -> {expected.name}")

        logger.info(f"{target_dir.name} dir is overwritten with {source_instructions}")

    return instructions_enabled


def setup_custom_agent(copilot_config: dict, entry: DatasetEntry, repo_path: Path, agent_type: AgentType) -> str | None:
    """
    Setup custom agents in the repository if available.
    """
    custom_agent_config: dict = copilot_config["agents"]
    custom_agent_enabled: bool = custom_agent_config["enabled"]

    if custom_agent_enabled:
        source_instructions: Path = _get_source_instructions_path(entry.repo)
        target_dir: Path = agent_type.get_target_dir(repo_path)
        copytree(source_instructions / "agents", target_dir / "agents", dirs_exist_ok=True)

        logger.info(f"Custom agents are set up from {source_instructions / 'agents'}")
        return custom_agent_config.get("name")

    return None


def _get_source_instructions_path(repo_name: str) -> Path:
    """
    Get path to source instruction folder for a repository.

    Instructions are stored in shared/instructions/ and used by both Copilot and Claude.

    Raises:
        FileNotFoundError: If instruction file doesn't exist
    """
    sanitized_name = repo_name.replace("/", "-")
    instructions_path = _config.paths.agent_share_dir / _config.file_patterns.copilot_instructions_dirname / sanitized_name

    if not instructions_path.exists():
        raise FileNotFoundError(f"Instruction folder not found: {instructions_path}\nExpected for repository: {repo_name}")

    return instructions_path


def copy_problem_statement_folder(entry: DatasetEntry, repo_path: Path) -> None:
    """
    Copy problem statement folder to the testbed repository root.

    This makes the problem statement (including any screenshots) accessible to Copilot during evaluation.

    Args:
        entry: Dataset entry containing problem_statement path
        repo_path: Path to testbed repository where folder will be copied
    """
    source_dir: Path = entry.problem_statement_dir
    dest_dir: Path = repo_path / _config.file_patterns.problem_statement_dest_dir

    if dest_dir.exists():
        rmtree(dest_dir)

    copytree(source_dir, dest_dir)
    logger.info(f"Copied problem statement folder from {source_dir} to {dest_dir}")
