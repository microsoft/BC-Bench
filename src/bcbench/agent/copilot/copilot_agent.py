"""GitHub Copilot CLI Agent implementation."""

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import yaml
from jinja2 import Template

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
) -> dict[str, float | int] | None:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Dictionary containing metrics extracted from the CLI output, or None if collection fails
    """
    config_file = Path(__file__).parent / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = _build_prompt(entry, repo_path, copilot_config)

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    # Resolve the copilot command path
    copilot_cmd = shutil.which("copilot")
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    try:
        result = subprocess.run(
            [
                copilot_cmd,
                "--allow-all-tools",  # required for non-interactive mode
                "--allow-all-paths",  # might be required for non-interactive mode, seems to hang when trying to access files outside allowed dirs
                "--disable-builtin-mcps",
                f"--model={model}",
                "--no-custom-instructions",
                "--log-level=debug",
                f"--log-dir={output_dir.resolve()}",
                "-p",
                prompt.replace("\r", "").replace("\n", " "),
            ],
            cwd=str(repo_path),
            capture_output=True,
            timeout=_config.timeout.github_copilot_cli,
            check=True,
        )

        # Write directly to stdout buffer as bytes to avoid console encoding issues
        if result.stdout:
            sys.stdout.buffer.write(result.stdout)
            sys.stdout.buffer.flush()
        if result.stderr:
            sys.stdout.buffer.write(result.stderr)
            sys.stdout.buffer.flush()
        logger.info(f"Copilot CLI run complete for: {entry.instance_id}")

        # Decode output for metrics parsing
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        # Metrics are typically in stderr
        stderr_lines = stderr.splitlines()
        return _parse_metrics(stderr_lines)
    except subprocess.TimeoutExpired:
        # timeout should not raise an exception, we will evaluate whatever copilot did so far
        logger.error(f"Copilot CLI timed out after {_config.timeout.github_copilot_cli} seconds")
        return None
    except subprocess.CalledProcessError as e:
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception as e:
        logger.exception(f"Unexpected error running Copilot CLI: {e}")
        raise


def _build_prompt(entry: DatasetEntry, repo_path: Path, config: dict) -> str:
    prompt_config = config.get("agent", {}).get("prompt", {})
    template_str = prompt_config.get("template")
    include_project_paths = prompt_config.get("include_project_paths")

    template = Template(template_str)
    return template.render(
        repo_path=repo_path,
        task=entry.get_task(),
        project_paths=", ".join(entry.project_paths),
        include_project_paths=include_project_paths,
    )


def _parse_metrics(output_lines: Sequence[str]) -> dict[str, float | int] | None:
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
