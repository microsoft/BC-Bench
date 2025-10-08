"""Mini BC Agent implementation using mini-swe-agent."""

import os
import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import typer
import yaml
from dotenv import load_dotenv

from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.dataset.dataset_loader import load_dataset_entries
from bcbench.core.utils import colored, GREY
from bcbench.core.logger import get_logger

load_dotenv()

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
        """BC-specific agent extending DefaultAgent."""

        def query(self) -> dict:
            """Query the model with current messages."""
            logger.debug(f"============================ Current step: {self.model.n_calls} =============================")
            return super().query()

        def parse_action(self, response: dict) -> dict:
            """Parse the action from the message. Returns the action."""
            logger.debug(f"Agent response content:\n{colored(response['content'], GREY)}")
            actions = re.findall(r"```powershell\s*\n(.*?)\n```", response["content"], re.DOTALL)
            if len(actions) == 1:
                return {"action": actions[0].strip(), **response}
            raise FormatError(self.render_template(self.config.format_error_template, actions=actions))

    return BCAgent


def run_mini_agent(
    dataset_path: Path,
    entry_id: Optional[str],
    version: Optional[str],
    repo_path: Path,
    use_container: bool = False,
    container_name: Optional[str] = None,
    username: str = "admin",
    password: Optional[str] = None,
    step_limit: int = 20,
    cost_limit: float = 1.0,
) -> None:
    if not entry_id and not version:
        logger.error("Must specify either --entry-id or --version")
        raise typer.Exit(code=1)

    if entry_id and version:
        logger.error("Cannot specify both --entry-id and --version")
        raise typer.Exit(code=1)

    if use_container:
        if not container_name:
            logger.error("--container-name is required when using --use-container")
            raise typer.Exit(code=1)

        if password is None:
            password = os.environ.get("BC_CONTAINER_PASSWORD")
            if password is None:
                logger.error("Password required when using --use-container. Set --password or BC_CONTAINER_PASSWORD env var")
                raise typer.Exit(code=1)

    try:
        entries = load_dataset_entries(dataset_path, entry_id=entry_id, version=version)
    except ValueError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)
    except Exception as exc:
        logger.error(f"Failed to load dataset entries: {exc}")
        raise typer.Exit(code=1)

    logger.info(f"Loaded {len(entries)} entry(ies) to process")

    results = []
    failed_count = 0

    for idx, entry in enumerate(entries, 1):
        logger.info(f"Processing entry {idx}/{len(entries)}: {entry.instance_id}")

        try:
            _run_single_entry(
                entry=entry,
                repo_path=repo_path,
                container_name=container_name or "",
                username=username,
                password=password or "",
                skip_env=use_container,
                step_limit=step_limit,
                cost_limit=cost_limit,
            )

            results.append({"instance_id": entry.instance_id, "status": "success"})
            logger.info(f"[OK] Successfully processed {entry.instance_id}")

        except Exception as exc:
            failed_count += 1
            error_msg = str(exc)
            results.append({"instance_id": entry.instance_id, "status": "failed", "error": error_msg})
            logger.error(f"✗ Failed to process {entry.instance_id}: {error_msg}")

    logger.info(f"\nSummary: {len(results) - failed_count}/{len(entries)} succeeded, {failed_count} failed")

    if failed_count > 0:
        raise typer.Exit(code=1)


def _run_single_entry(
    entry: DatasetEntry,
    repo_path: Path,
    container_name: str,
    username: str,
    password: str,
    skip_env: bool,
    step_limit: int,
    cost_limit: float,
) -> None:
    """Run mini-bc-agent on a single entry."""

    task: str = entry.get_task()

    config_file = Path(__file__).parent / "bc_agent_config.yaml"
    _config = yaml.safe_load(config_file.read_text())
    agent_config = _config.get("agent", {})
    agent_config["step_limit"] = step_limit
    agent_config["cost_limit"] = cost_limit

    # Lazy import and create agent
    from minisweagent.models.litellm_model import LitellmModel
    from bcbench.agent.mini.bc_environment import BCEnvironment

    BCAgent = _create_bc_agent_class()

    agent = BCAgent(
        LitellmModel(model_name="azure/gpt-4.1"),
        BCEnvironment(
            container_name=container_name,
            nav_repo_path=str(repo_path),
            username=username,
            password=password,
            project_paths=entry.project_paths,
            cwd=str(repo_path),
            enable_bc_tools=not skip_env,
        ),
        **agent_config,
    )

    agent.run(task)

    # TODO: Save generated patch to entry_output_dir?
    logger.info(f"Agent completed for {entry.instance_id} after {agent.model.n_calls} steps")
