import json
import logging
from pathlib import Path

import typer
import yaml, re
from minisweagent.agents.default import DefaultAgent, FormatError
from minisweagent.models.litellm_model import LitellmModel

from bc_environment import BCEnvironment
from dataset_entry import DatasetEntry
from utils import DATASET_PATH, colored, GREY

logging.basicConfig(
    level=logging.WARNING,  # Set root logger to WARNING to suppress underlying packages
    format='[%(asctime)s] %(name)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

def load_entry_from_dataset(instance_id: str) -> DatasetEntry:
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line.strip())
            if data.get("instance_id") == instance_id:
                return DatasetEntry.from_json(data)

    raise ValueError(f"Entry with instance_id '{instance_id}' not found in dataset")

def build_task_description(entry: DatasetEntry) -> str:
    task = entry.problem_statement
    if entry.hints_text:
        task += f"\n\n## Additional Hints\n{entry.hints_text}"
    logger.info(f"Task description:\n{colored(task, GREY)}")
    return task

class BCAgent(DefaultAgent):
    def query(self) -> dict:
        # logger.debug(f"Current messages:\n{self.messages}")
        logger.debug(f"============================ Current step: {self.model.n_calls} =============================")
        return super().query()

    def parse_action(self, response: dict) -> dict:
        """Parse the action from the message. Returns the action."""
        logger.debug(f"Agent response content:\n{colored(response['content'], GREY)}")
        actions = re.findall(r"```powershell\s*\n(.*?)\n```", response["content"], re.DOTALL)
        if len(actions) == 1:
            return {"action": actions[0].strip(), **response}
        raise FormatError(self.render_template(self.config.format_error_template, actions=actions))

app = typer.Typer()

@app.command()
def main(
    instance_id: str = typer.Argument('microsoftInternal__NAV-210528', help="Instance ID from the dataset"),
    nav_repo_path: str = typer.Argument('C:\\depot\\NAV', help="Path to NAV repository"),
    use_container: bool = typer.Option(False, help="Whether to use containerized BC environment"),
    container_name: str = typer.Option('bcbench-265', help="BC container name"),
    username: str = typer.Option("admin", help="Username for BC container environment"),
    password: str = typer.Option("123456", help="Password for BC container environment"),
    step_limit: int = typer.Option(20, help="Maximum number of agent steps"),
    cost_limit: float = typer.Option(1.0, help="Maximum cost limit for agent"),
):
    entry: DatasetEntry = load_entry_from_dataset(instance_id)

    config_file: Path = Path(__file__).parent / 'bc_agent_config.yaml'
    _config = yaml.safe_load(config_file.read_text())
    agent_config = _config.get("agent", {})
    agent_config['step_limit'] = step_limit
    agent_config['cost_limit'] = cost_limit

    task: str = build_task_description(entry)

    agent = BCAgent(
        LitellmModel(model_name = 'azure/gpt-4.1'),
        BCEnvironment(
            container_name=container_name,
            nav_repo_path=nav_repo_path,
            username=username,
            password=password,
            project_paths=entry.project_paths,
            cwd=nav_repo_path,
            enable_bc_tools=use_container
        ),
        **agent_config
    )

    agent.run(task)

if __name__ == "__main__":
    app()
