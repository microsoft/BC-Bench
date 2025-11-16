from pathlib import Path
from shutil import copytree, rmtree

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def setup_instructions_from_config(copilot_config: dict, entry: DatasetEntry, repo_path: Path, agent_dir: Path) -> bool:
    """
    Setup custom instructions from config if enabled.

    Args:
        copilot_config: Copilot agent configuration dictionary
        entry: Dataset entry containing repo information
        repo_path: Path to repository where instructions will be copied
        agent_dir: Path to copilot agent directory containing instruction templates

    Returns:
        True if instructions are enabled, False otherwise

    Raises:
        AgentError: If instructions are enabled but template not found
    """
    instructions_config: dict = copilot_config["instructions"]
    instructions_enabled: bool = instructions_config["enabled"]

    if instructions_enabled:
        try:
            source_instructions_path = _get_source_instructions_path(entry.repo, agent_dir)
            _setup_custom_instructions(repo_path, source_instructions_path)
            logger.info(f"Custom instructions enabled: copied instructions from {source_instructions_path}")
        except FileNotFoundError as e:
            logger.error(str(e))
            raise AgentError(f"Custom instructions enabled but template not found for repo: {entry.repo}") from None

    return instructions_enabled


def _setup_custom_instructions(repo_path: Path, instructions_source: Path) -> None:
    """
    Copy all files from instructions_source to repo's .github directory.
    Removes existing .github directory if present.
    """
    github_dir = repo_path / ".github"
    if github_dir.exists():
        rmtree(github_dir)

    copytree(instructions_source, github_dir)
    logger.debug(f"Successfully copied all contents from {instructions_source} to {github_dir}")


def _get_source_instructions_path(repo_name: str, agent_dir: Path) -> Path:
    """
    Get path to source instruction folder for a repository.

    Raises:
        FileNotFoundError: If instruction file doesn't exist
    """
    sanitized_name = repo_name.replace("/", "-")
    instructions_path = agent_dir / _config.file_patterns.copilot_instructions_dirname / sanitized_name

    if not instructions_path.exists():
        raise FileNotFoundError(f"Instruction folder not found: {instructions_path}\nExpected for repository: {repo_name}")

    return instructions_path
