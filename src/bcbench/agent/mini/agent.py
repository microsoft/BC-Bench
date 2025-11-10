"""Mini BC Agent implementation using mini-swe-agent."""

import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import ConfigurationError
from bcbench.logger import get_logger

# Lazy imports to avoid mini-swe-agent startup message for non-agent commands
if TYPE_CHECKING:
    from minisweagent.agents.default import DefaultAgent, FormatError  # noqa: F401
    from minisweagent.models.litellm_model import LitellmModel  # noqa: F401

    from bcbench.agent.mini.bc_environment import BCEnvironment  # noqa: F401

logger = get_logger(__name__)
_config = get_config()


def _create_bc_agent_class():
    """Lazy creation of BCAgent class to avoid importing mini-swe-agent at module load."""
    from minisweagent.agents.default import DefaultAgent, FormatError

    class BCAgent(DefaultAgent):
        def query(self) -> dict:
            """Overwrite for logging"""
            if self.model.n_calls + 1 < self.config.step_limit:
                logger.info(f"Step {self.model.n_calls + 1}")
            return super().query()

        def parse_action(self, response: dict) -> dict:
            """Overwrite for logging and switching from bash to powershell"""
            response_content: str = response["content"]
            if len(response_content) <= 200:
                logger.info(f"Agent response:\n{response_content}")
            else:
                logger.info(f"Agent response (truncated from {len(response_content)} chars):\n{response_content[:197]}...")

            actions = re.findall(r"```powershell\s*\n(.*?)\n```", response_content, re.DOTALL)
            if len(actions) == 1:
                return {"action": actions[0].strip(), **response}
            raise FormatError(self.render_template(self.config.format_error_template, actions=actions))

    return BCAgent


def run_mini_agent(
    entry: DatasetEntry,
    repo_path: Path,
    model: str,
    container_name: str | None = None,
    username: str = "admin",
    password: str | None = None,
    output_dir: Path | None = None,
) -> dict[str, float | int] | None:
    """Run mini-bc-agent on a single dataset entry.

    Returns:
        Dictionary containing metrics (agent_execution_time, prompt_tokens, completion_tokens),
        or None if metric extraction fails.
    """
    config_file = Path(__file__).parent / "config.yaml"
    mini_bc_config = yaml.safe_load(config_file.read_text())
    agent_config = mini_bc_config.get("agent", {})
    env_config = mini_bc_config.get("environment", {})

    enable_bc_tools: bool = env_config.get("enable_bc_tools")
    if enable_bc_tools and (not container_name or not password):
        raise ConfigurationError("container_name and password are required when enable_bc_tools is True")

    logger.info(f"Running mini-bc-agent on: {entry.instance_id}")

    task: str = entry.get_task()

    # Lazy import and create agent
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.run.utils.save import save_traj

    from bcbench.agent.mini.bc_environment import BCEnvironment

    BCAgent = _create_bc_agent_class()

    agent = BCAgent(
        LitellmModel(model_name=model),
        BCEnvironment(
            container_name=container_name,
            repo_path=str(repo_path),
            username=username,
            password=password,
            project_paths=entry.project_paths,
            cwd=str(repo_path),
            include_project_paths=env_config.get("include_project_paths"),
            enable_bc_tools=enable_bc_tools,
            version=entry.environment_setup_version,
        ),
        **agent_config,
    )

    start_time = time.time()
    exit_status, result = agent.run(task)
    execution_time = time.time() - start_time

    if output_dir:
        traj_file: Path = output_dir / f"{entry.instance_id}{_config.file_patterns.trajectory_pattern}"
        save_traj(agent, traj_file, exit_status=exit_status, result=result)

    logger.info(f"mini-bc-agent run complete for: {entry.instance_id} after {agent.model.n_calls} steps")

    return _extract_metrics(agent, execution_time)


def _extract_metrics(agent, execution_time: float) -> dict[str, float | int] | None:
    """Extract metrics from agent execution.

    Args:
        agent: The BCAgent instance after execution
        execution_time: Total execution time in seconds

    Returns:
        Dictionary with agent_execution_time and optionally prompt_tokens/completion_tokens,
        or None if extraction fails
    """
    try:
        metrics: dict[str, float | int] = {
            "agent_execution_time": execution_time,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        for message in agent.messages:
            if "role" in message and message["role"] == "assistant":
                extra = message.get("extra", {})
                response = extra.get("response", {})
                usage = response.get("usage", {})
                if "prompt_tokens" in usage and "completion_tokens" in usage:
                    metrics["prompt_tokens"] += usage["prompt_tokens"]
                    metrics["completion_tokens"] += usage["completion_tokens"]

        logger.info(f"Extracted metrics: {metrics}")
        return metrics

    except Exception as e:
        logger.warning(f"Failed to extract metrics from agent: {e}")
        return None
