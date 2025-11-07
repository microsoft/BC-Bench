"""GitHub Copilot CLI Agent implementation."""

import re
import subprocess
from collections import deque
from pathlib import Path

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def run_copilot_agent(
    entry: DatasetEntry,
    model: str,
    repo_path: Path,
    output_dir: Path,
    include_project_paths: bool = False,
) -> dict[str, float | int] | None:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Dictionary containing metrics extracted from the CLI output, or None if collection fails
    """
    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = _build_prompt(entry, repo_path, include_project_paths)

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    process = None
    # Use collections.deque with maxlen to keep only last few lines for metric parsing
    output_buffer: deque[str] = deque(maxlen=20)

    try:
        process = subprocess.Popen(
            [
                "copilot",
                "--allow-all-tools",  # required for non-interactive mode
                "--allow-all-paths",  # might be required for non-interactive mode, seems to hang when trying to access files outside allowed dirs
                "--disable-builtin-mcps",
                f"--model={model}",
                "--no-custom-instructions",
                "--log-level=debug",
                f"--log-dir={output_dir}",
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
                output_buffer.append(line)

        return_code = process.wait(timeout=_config.timeout.github_copilot_cli)

        if return_code == 0:
            logger.info("Copilot CLI completed successfully")
        else:
            logger.warning(f"Copilot CLI exited with code {return_code}")
            raise subprocess.CalledProcessError(return_code, "copilot")

    except subprocess.TimeoutExpired:
        # timeout should not raise an exception, we will evaluate whatever copilot did so far
        logger.error(f"Copilot CLI timed out after {_config.timeout.github_copilot_cli} seconds")
    except subprocess.CalledProcessError as e:
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception as e:
        logger.error(f"Unexpected error running Copilot CLI: {e}")
        raise
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait()

    logger.info(f"Copilot CLI run complete for: {entry.instance_id}")

    return _parse_metrics(list(output_buffer))


def _build_prompt(entry: DatasetEntry, repo_path: Path, include_project_paths: bool) -> str:
    project_paths: str = ", ".join(entry.project_paths)

    return f"""This is a non-interactive session. You are working with a Business Central (AL) code repository at {repo_path}.

Task: Fix the issue described below {"in the following projects: " + project_paths if include_project_paths else ""}

Important constraints:
- Do NOT modify any testing logic or test files
- Focus solely on fixing the reported issue
- Do NOT try to build or run tests, just provide the code changes needed

Issue details:
{entry.get_task()}
"""


def _parse_metrics(output_lines: list[str]) -> dict[str, float | int] | None:
    """Parse metrics from Copilot CLI output.
    This is highly delicate and depends on the exact formatting of the CLI output.

    Expected output format at the end:
        Total usage est:       1 Premium request
        Total duration (API):  34.5s
        Total duration (wall): 3m 55.1s
        Total code changes:    2 lines added, 1 lines removed
        Usage by model:
            gpt-5                125.5k input, 3.6k output, 0 cache read, 0 cache write (Est. 1 Premium request)
    """
    if not output_lines:
        logger.warning("No output lines to parse metrics from")
        return None

    output_text = "".join(output_lines)
    logger.debug(f"Parsing metrics from output:\n{output_text}")

    metrics: dict[str, float | int] = {}

    try:
        duration_match = re.search(r"Total duration \(wall\):\s*(?:(\d+)m\s*)?(\d+(?:\.\d+)?)s", output_text)
        if duration_match:
            minutes = int(duration_match.group(1)) if duration_match.group(1) else 0
            seconds = float(duration_match.group(2))
            metrics["agent_execution_time"] = minutes * 60 + seconds

        usage_match = re.search(r"(\d+(?:\.\d+)?[km]?)\s+input,\s*(\d+(?:\.\d+)?[km]?)\s+output", output_text)
        if usage_match:
            input_str = usage_match.group(1)
            output_str = usage_match.group(2)

            def parse_token_count(s: str) -> int:
                if s.endswith("m"):
                    return int(float(s[:-1]) * 1000000)
                if s.endswith("k"):
                    return int(float(s[:-1]) * 1000)
                return int(float(s))

            metrics["prompt_tokens"] = parse_token_count(input_str)
            metrics["completion_tokens"] = parse_token_count(output_str)

        if metrics:
            logger.info(f"Parsed metrics: {metrics}")
            return metrics

        logger.warning("No metrics found in output")
        return None

    except Exception as e:
        logger.error(f"Failed to parse metrics from output: {e}")
        return None
