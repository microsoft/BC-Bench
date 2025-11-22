"""GitHub Copilot CLI Agent implementation."""

import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from bcbench.agent.copilot.mcp import build_mcp_config
from bcbench.agent.copilot.metrics import parse_metrics
from bcbench.agent.copilot.prompt import build_prompt
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_custom_agent, setup_instructions_from_config
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()


def run_copilot_agent(entry: DatasetEntry, model: str, category: EvaluationCategory, repo_path: Path, output_dir: Path) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    config_file = Path(__file__).parent / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot CLI on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, copilot_config, category)
    mcp_config_json, mcp_server_names = build_mcp_config(copilot_config, repo_path)
    instructions_enabled: bool = setup_instructions_from_config(copilot_config, entry, repo_path)
    custom_agent: str | None = setup_custom_agent(copilot_config, entry, repo_path)
    config = ExperimentConfiguration(mcp_servers=mcp_server_names, custom_instructions=instructions_enabled, custom_agent=custom_agent)

    logger.info(f"Executing Copilot CLI in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    copilot_cmd = shutil.which("copilot")  # Resolve the copilot command path
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    try:
        cmd_args = [
            copilot_cmd,
            "--allow-all-tools",  # required for non-interactive mode
            "--allow-all-paths",  # might be required for non-interactive mode, seems to hang when trying to access files outside allowed dirs
            "--disable-builtin-mcps",
            f"--model={model}",
            "--log-level=debug",
            "--disable-parallel-tools-execution",
            f"--log-dir={output_dir.resolve()}",
            f"--prompt={prompt.replace('\r', '').replace('\n', ' ')}",
        ]
        if not instructions_enabled:
            cmd_args.append("--no-custom-instructions")
        if mcp_config_json:
            cmd_args.append(f"--additional-mcp-config={mcp_config_json}")
        if custom_agent:
            cmd_args.append(f"--agent={custom_agent}")

        logger.debug(f"Copilot command args: {cmd_args}")

        result = subprocess.run(
            cmd_args,
            cwd=str(repo_path),
            stderr=subprocess.PIPE,  # only capture stderr where metrics are printed
            timeout=_config.timeout.github_copilot_cli,
            check=True,
        )

        if result.stderr:
            sys.stdout.buffer.write(result.stderr)
            sys.stdout.buffer.flush()
        logger.info(f"Copilot CLI run complete for: {entry.instance_id}")

        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        stderr_lines = stderr.splitlines()
        metrics = parse_metrics(stderr_lines)
        return metrics, config
    except subprocess.TimeoutExpired:
        logger.error(f"Copilot CLI timed out after {_config.timeout.github_copilot_cli} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.github_copilot_cli)
        raise AgentTimeoutError("Copilot CLI timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.error(f"Copilot CLI execution failed with error {e.stderr}")
        raise AgentError(f"Copilot CLI execution failed: {e}") from None
    except Exception as e:
        logger.exception(f"Unexpected error running Copilot CLI: {e}")
        raise
