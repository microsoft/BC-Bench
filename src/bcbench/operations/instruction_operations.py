from pathlib import Path
from shutil import copytree, rmtree

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def setup_instructions_from_config(copilot_config: dict, entry: DatasetEntry, repo_path: Path) -> bool:
    """
    Setup custom instructions from config if enabled.

    Args:
        copilot_config: Copilot agent configuration dictionary
        entry: Dataset entry containing repo information
        repo_path: Path to repository where instructions will be copied

    Returns:
        True if instructions are enabled, False otherwise

    Raises:
        AgentError: If instructions are enabled but template not found
    """
    instructions_config: dict = copilot_config["instructions"]
    instructions_enabled: bool = instructions_config["enabled"]

    if instructions_enabled:
        try:
            source_instructions_path = _get_source_instructions_path(entry.repo)
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


def setup_custom_agent(repo_path: Path, repo_name: str) -> None:
    """
    Setup custom agent instructions in the repository if available.
    Assumptions: They will not be automatically loaded unless specified, so we can copy them by default.

    Args:
        repo_path: Path to the repository where instructions will be copied
        repo_name: Name of the repository (e.g., "org/repo")
    """
    logger.info(f"Setting up custom agents for repository: {repo_name}")
    source_instructions_path = _get_source_instructions_path(repo_name)
    copytree(source_instructions_path / "agents", repo_path / ".github" / "agents", dirs_exist_ok=True)


def _get_source_instructions_path(repo_name: str) -> Path:
    """
    Get path to source instruction folder for a repository.

    Raises:
        FileNotFoundError: If instruction file doesn't exist
    """
    sanitized_name = repo_name.replace("/", "-")
    instructions_path = _config.paths.agent_dir / _config.file_patterns.copilot_instructions_dirname / sanitized_name

    if not instructions_path.exists():
        raise FileNotFoundError(f"Instruction folder not found: {instructions_path}\nExpected for repository: {repo_name}")

    return instructions_path
