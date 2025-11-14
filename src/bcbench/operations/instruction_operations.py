from pathlib import Path
from shutil import copy2, rmtree

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
            logger.info(f"Custom instructions enabled: copied instructions from {source_instructions_path}")
        except FileNotFoundError as e:
            logger.error(str(e))
            raise AgentError(f"Custom instructions enabled but template not found for repo: {entry.repo}") from None

    return instructions_enabled


def _setup_custom_instructions(repo_path: Path, instructions_source: Path) -> Path:
    """
    Copy custom instructions file to repo's .github directory.
    Also copies path-specific instructions folder if present.

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

    # Copy path-specific instructions folder if present
    source_instructions_dir = instructions_source.parent / "instructions"
    if source_instructions_dir.exists() and source_instructions_dir.is_dir():
        target_instructions_dir = github_dir / "instructions"

        # Remove existing instructions folder if present
        if target_instructions_dir.exists():
            rmtree(target_instructions_dir)

        # Copy all *.instructions.md files (flattened)
        target_instructions_dir.mkdir(parents=True, exist_ok=True)
        instruction_files = list(source_instructions_dir.rglob("*.instructions.md"))

        if instruction_files:
            for file in instruction_files:
                copy2(file, target_instructions_dir / file.name)
            logger.info(f"Copied {len(instruction_files)} path-specific instruction file(s) to {target_instructions_dir}")
        else:
            logger.warning(f"Instructions folder exists at {source_instructions_dir} but contains no *.instructions.md files")
    else:
        logger.warning(f"No path-specific instructions folder found at {source_instructions_dir}")

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
