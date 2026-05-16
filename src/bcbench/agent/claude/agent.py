import json
import shutil
import subprocess
from pathlib import Path

import yaml

from bcbench.agent.claude.metrics import parse_metrics
from bcbench.agent.shared import build_mcp_config, build_prompt, parse_tool_usage_from_hooks
from bcbench.config import get_config
from bcbench.dataset import BaseDatasetEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_agent_skills, setup_custom_agent, setup_hooks, setup_instructions_from_config
from bcbench.types import AgentMetrics, AgentType, EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()


def run_claude_code(
    entry: BaseDatasetEntry, model: str, category: EvaluationCategory, repo_path: Path, output_dir: Path, al_mcp: bool = False, container_name: str = "bcbench"
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run Claude Code on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used
    """
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    claude_config = yaml.safe_load(config_file.read_text())

    is_code_review_bcapps = category == EvaluationCategory.CODE_REVIEW and entry.repo == "microsoft/BCApps"
    if is_code_review_bcapps:
        claude_config.setdefault("instructions", {})["enabled"] = True
        claude_config.setdefault("skills", {})["enabled"] = True

    logger.info(f"Running Claude Code on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, claude_config, category, al_mcp=al_mcp)
    mcp_config_json, mcp_server_names = build_mcp_config(claude_config, entry, repo_path, al_mcp=al_mcp, container_name=container_name)
    instructions_enabled: bool = setup_instructions_from_config(claude_config, entry, repo_path, agent_type=AgentType.CLAUDE)
    skills_enabled: bool = setup_agent_skills(claude_config, entry, repo_path, agent_type=AgentType.CLAUDE)
    custom_agent: str | None = setup_custom_agent(claude_config, entry, repo_path, agent_type=AgentType.CLAUDE)
    tool_log_path: Path = setup_hooks(repo_path, AgentType.CLAUDE, output_dir)
    config = ExperimentConfiguration(
        mcp_servers=mcp_server_names,
        custom_instructions=instructions_enabled,
        skills_enabled=skills_enabled,
        custom_agent=custom_agent,
    )

    logger.info(f"Executing Claude Code in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    claude_cmd = shutil.which("claude")
    if not claude_cmd:
        raise AgentError("Claude Code not found in PATH. Please ensure it is installed and available.")

    try:
        cmd_args = [
            claude_cmd,
            "--output-format=json",
            "--strict-mcp-config",  # Only use MCP servers from --mcp-config, ignoring all other MCP configurations
            f"--model={model}",
            "--permission-mode=bypassPermissions",  # bypassPermissions is needed to use tools and mcp servers
            "--disallowedTools",
            "WebFetch",
            "Bash(curl *)",
            "Bash(wget *)",
        ]
        if mcp_config_json:
            cmd_args.append(f"--mcp-config={mcp_config_json}")
        if custom_agent:
            cmd_args.append(f"--agent={custom_agent}")
        cmd_args.extend(
            [
                "--print",  # Non-interactive mode
                prompt.replace("\r", "").replace("\n", " "),
            ]
        )

        logger.debug(f"Claude Code command args: {cmd_args}")

        result = subprocess.run(
            cmd_args,
            cwd=str(repo_path),
            timeout=_config.timeout.agent_execution,
            check=True,
            capture_output=True,
        )

        stdout: str = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        logger.debug(f"Claude Code raw output: {stdout}")

        metrics = None
        for line in stdout.splitlines():
            striped_line: str = line.strip()
            if striped_line:
                try:
                    data = json.loads(striped_line)
                    if "result" in data:
                        logger.info(data["result"])
                        metrics = parse_metrics(data)
                except json.JSONDecodeError:
                    logger.warning(f"Skipping non-JSON line: {striped_line}")

        tool_usage: dict[str, int] | None = parse_tool_usage_from_hooks(tool_log_path)
        if metrics and tool_usage:
            metrics = metrics.model_copy(update={"tool_usage": tool_usage})

        return metrics, config
    except subprocess.TimeoutExpired:
        logger.exception(f"Claude Code timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("Claude Code timed out", metrics=metrics, config=config) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"Claude Code execution failed with error {e.stderr}")
        raise AgentError(f"Claude Code execution failed: {e.stderr}") from e
    except Exception:
        logger.exception("Unexpected error running Claude Code")
        raise
