"""Mini BC Agent implementation using mini-swe-agent."""

import re
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
    enable_bc_tools: bool = False,
    container_name: str | None = None,
    username: str = "admin",
    password: str | None = None,
    step_limit: int = 20,
    cost_limit: float = 1.0,
    output_dir: Path | None = None,
) -> None:
    """Run mini-bc-agent on a single dataset entry."""
    if enable_bc_tools:
        if not container_name:
            raise ConfigurationError("container_name is required when enable_bc_tools is True")

        config = get_config()
        password = config.resolve_password(password)

    logger.info(f"Running mini-bc-agent on: {entry.instance_id}")

    task: str = entry.get_task()

    config_file = Path(__file__).parent / "bc_agent_config.yaml"
    _config = yaml.safe_load(config_file.read_text())
    agent_config = _config.get("agent", {})
    agent_config["step_limit"] = step_limit
    agent_config["cost_limit"] = cost_limit

    # Lazy import and create agent
    from minisweagent.models.litellm_model import LitellmModel
    from minisweagent.run.utils.save import save_traj

    from bcbench.agent.mini.bc_environment import BCEnvironment

    BCAgent = _create_bc_agent_class()

    agent = BCAgent(
        LitellmModel(model_name="azure/gpt-4.1"),
        BCEnvironment(
            container_name=container_name,
            repo_path=str(repo_path),
            username=username,
            password=password,
            project_paths=entry.project_paths,
            cwd=str(repo_path),
            enable_bc_tools=enable_bc_tools,
            version=entry.environment_setup_version,
        ),
        **agent_config,
    )

    exit_status, result = agent.run(task)
    if output_dir:
        traj_file: Path = output_dir / f"{entry.instance_id}.traj.json"
        save_traj(agent, traj_file, exit_status=exit_status, result=result)

    logger.info(f"mini-bc-agent run complete for: {entry.instance_id} after {agent.model.n_calls} steps")
