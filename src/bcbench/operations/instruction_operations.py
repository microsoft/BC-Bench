from pathlib import Path
from shutil import copy2

from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)


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
            logger.info(f"Custom instructions enabled: copied from {source_instructions_path} to {repo_path / '.github' / 'copilot-instructions.md'}")
        except FileNotFoundError as e:
            logger.error(str(e))
            raise AgentError(f"Custom instructions enabled but template not found for repo: {entry.repo}") from None

    return instructions_enabled


def _setup_custom_instructions(repo_path: Path, instructions_source: Path) -> Path:
    """
    Copy custom instructions file to repo's .github directory.

    Returns:
        Path to the created instruction file

    Raises:
        FileNotFoundError: If instruction file doesn't exist
    """
    if not instructions_source.exists():
        raise FileNotFoundError(f"Instruction file not found: {instructions_source}")

    github_dir = repo_path / ".github"
    github_dir.mkdir(parents=True, exist_ok=True)

    target_path = github_dir / "copilot-instructions.md"
    copy2(instructions_source, target_path)
    return target_path


def _get_source_instructions_path(repo_name: str, agent_dir: Path) -> Path:
    """
    Get path to source instruction file for a repository.

    Raises:
        FileNotFoundError: If instruction file doesn't exist
    """
    sanitized_name = repo_name.replace("/", "-")
    instructions_path = agent_dir / "instructions" / sanitized_name / "copilot-instructions.md"

    if not instructions_path.exists():
        raise FileNotFoundError(f"Instruction file not found: {instructions_path}\nExpected for repository: {repo_name}")

    return instructions_path
