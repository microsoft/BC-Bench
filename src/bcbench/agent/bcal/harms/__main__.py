from bcbench_core.logs import setup_logging

from bcbench.agent.bcal.harms.cli import app
from bcbench.config import get_config

setup_logging(app_logger="bcbench", debug=get_config().env.runner_debug, github_actions=get_config().env.github_actions)
app()
