import json
import shutil
import subprocess
from pathlib import Path

import yaml

from bcbench.agent.claude.metrics import parse_metrics
from bcbench.agent.shared import build_prompt
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()


def _print_result_from_json(json_output: str) -> None:
    """Print the result summary from Claude Code JSON output."""
    try:
        data = json.loads(json_output)
        # Only print the result summary, not the full JSON
        if "result" in data:
            print(data["result"], flush=True)
    except json.JSONDecodeError:
        logger.warning("Could not parse JSON output to extract result")


def run_claude_code(entry: DatasetEntry, model: str, category: EvaluationCategory, repo_path: Path, output_dir: Path) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run Claude Code on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    claude_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running Claude Code on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, claude_config, category)

    # Baseline configuration: no MCP servers, no custom instructions
    config = ExperimentConfiguration(
        mcp_servers=None,
        custom_instructions=False,
        custom_agent=None,
    )

    logger.info(f"Executing Claude Code in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        raise AgentError("Claude Code not found in PATH. Please ensure it is installed and available.")

    try:
        cmd_args = [
            claude_cmd,
            "--print",  # Non-interactive mode
            "--output-format=json",
            "--no-session-persistence",
            # "--verbose",  # required for when using --print, --output-format=stream-json
            "--strict-mcp-config",  # Only use MCP servers from --mcp-config, ignoring all other MCP configurations
            f"--model={model}",
            "--permission-mode=acceptEdits",  # acceptEdits instead of bypassPermissions for now, avoid unexpected behavior
            prompt.replace("\r", "").replace("\n", " "),
        ]

        logger.debug(f"Claude Code command args: {cmd_args}")

        result = subprocess.run(
            cmd_args,
            cwd=str(repo_path),
            timeout=_config.timeout.github_copilot_cli,  # Reuse copilot timeout for now
            check=True,
            capture_output=True,
        )

        stdout: str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        _print_result_from_json(stdout)

        metrics = parse_metrics(stdout)

        return metrics, config
    except subprocess.TimeoutExpired:
        logger.error(f"Claude Code timed out after {_config.timeout.github_copilot_cli} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.github_copilot_cli)
        raise AgentTimeoutError("Claude Code timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.error(f"Claude Code execution failed with errorP {e.stderr}")
        raise AgentError(f"Claude Code execution failed: {e.stderr}") from e
    except Exception as e:
        logger.exception(f"Unexpected error running Claude Code: {e}")
        raise
