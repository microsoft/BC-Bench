"""GitHub Copilot CLI Agent implementation."""

import subprocess
from pathlib import Path

from bcbench.dataset import DatasetEntry
from bcbench.logger import get_logger

logger = get_logger(__name__)


def run_copilot_agent(
    entry: DatasetEntry,
    repo_path: Path,
    output_dir: Path | None = None,
) -> None:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Args:
        entry_id: ID of the entry to run
        repo_path: Path to the repository
        output_dir: Optional directory to save output files (unused, kept for API compatibility)
    """
    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = _build_prompt(entry, repo_path)

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    process = None
    try:
        process = subprocess.Popen(
            [
                "copilot",
                "--allow-all-tools",  # required for non-interactive mode
                "--allow-all-paths",  # might be required for non-interactive mode, seems to hang when trying to access files outside allowed dirs
                "--disable-builtin-mcps",
                "--no-custom-instructions",
                "--log-level",
                "debug",
                "-p",
                prompt.replace("\r", "").replace("\n", " "),
            ],
            cwd=str(repo_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            shell=True,  # Required on Windows to resolve npm global commands
        )

        if process.stdout:
            for line in process.stdout:
                print(line, end="", flush=True)

        return_code = process.wait(timeout=60 * 10)

        if return_code == 0:
            logger.info("Copilot CLI completed successfully")
        else:
            logger.warning(f"Copilot CLI exited with code {return_code}")
            raise subprocess.CalledProcessError(return_code, "copilot")

    except subprocess.TimeoutExpired:
        if process:
            process.kill()
        logger.error("Copilot CLI timed out after 600 seconds")
        raise
    except Exception as e:
        logger.error(f"Error running Copilot CLI: {e}")
        raise

    logger.info(f"Copilot CLI run complete for: {entry.instance_id}")


def _build_prompt(entry: DatasetEntry, repo_path: Path) -> str:
    project_paths: str = ", ".join(entry.project_paths)

    return f"""This is a non-interactive session. You are working with a Business Central (AL) code repository at {repo_path}.

Task: Fix the issue described below in the projects at: {project_paths}

Important constraints:
- Do NOT modify any testing logic or test files
- Focus solely on fixing the reported issue
- Do NOT try to build or run tests, just provide the code changes needed

Issue details:
{entry.get_task()}
"""
