"""bc-al dotnet tool agent for NL2AL evaluation."""

import shutil
import subprocess
import time
from pathlib import Path

import yaml

from bcbench.agent.shared import build_prompt
from bcbench.config import get_config
from bcbench.dataset import NL2ALEntry
from bcbench.exceptions import AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()


def run_bcal_agent(
    entry: NL2ALEntry,
    output_dir: Path,
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    agent_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running bc-al on: {entry.instance_id}")

    prompt: str = build_prompt(entry, output_dir, agent_config, EvaluationCategory.NL2AL)

    bc_al_cmd = shutil.which("bc-al")  # TODO: download from DynamicsSMBTest feed, Microsoft.BusinessCentral.BCal.CLI
    if not bc_al_cmd:
        raise AgentError("bc-al not found in PATH. Please ensure the dotnet tool is installed.")

    cmd_args = [
        bc_al_cmd,
        f"--workspace={output_dir.resolve()}",
        f"--prompt={prompt}",
    ]

    logger.info(f"Executing bc-al in directory: {output_dir}")
    logger.debug(f"Using prompt:\n{prompt}")
    logger.debug(f"bc-al command args: {cmd_args}")

    try:
        start = time.monotonic()
        subprocess.run(
            cmd_args,
            cwd=str(output_dir),
            timeout=_config.timeout.agent_execution,
            check=True,
        )
        execution_time = time.monotonic() - start

        logger.info(f"bc-al run complete for: {entry.instance_id}")
        return AgentMetrics(execution_time=execution_time), ExperimentConfiguration()
    except subprocess.TimeoutExpired:
        logger.exception(f"bc-al timed out after {_config.timeout.agent_execution} seconds")
        metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
        raise AgentTimeoutError("bc-al timed out", metrics=metrics, config=ExperimentConfiguration()) from None
    except subprocess.CalledProcessError as e:
        logger.exception(f"bc-al execution failed: {e.stderr}")
        raise AgentError(f"bc-al execution failed: {e}") from None
    except Exception:
        logger.exception("Unexpected error running bc-al")
        raise
