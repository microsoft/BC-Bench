import logging
import subprocess
from collections.abc import Mapping
from pathlib import Path

from bcbench_core.agent.copilot.cli import run_copilot_cli
from bcbench_core.agent.copilot.types import CopilotOptions, CopilotProcessError, CopilotTimeoutError
from bcbench_core.agent.env import agent_subprocess_env
from bcbench_core.agent.metrics import AgentMetrics

logger = logging.getLogger(__name__)


def invoke_copilot(
    prompt: str,
    model: str,
    work_dir: Path,
    timeout: int,
    env: Mapping[str, str],
    options: CopilotOptions | None = None,
) -> tuple[AgentMetrics | None, str]:
    """Run a Copilot session; tools and custom instructions are disabled by default."""
    options = options or CopilotOptions()
    overrides = None if options.workspace_mcp is None else {"GITHUB_COPILOT_PROMPT_MODE_WORKSPACE_MCP": str(options.workspace_mcp).lower()}
    process_env = agent_subprocess_env(env, overrides)
    logger.info("Executing Copilot CLI in directory: %s", work_dir)

    try:
        return run_copilot_cli(prompt=prompt, model=model, work_dir=work_dir, timeout=timeout, env=process_env, options=options)
    except subprocess.TimeoutExpired as exc:
        logger.exception("Copilot CLI timed out after %s seconds", timeout)
        raise CopilotTimeoutError(timeout, stdout=exc.stdout, stderr=exc.stderr) from exc
    except subprocess.CalledProcessError as exc:
        logger.exception("Copilot CLI execution failed: %s", exc.stderr)
        raise CopilotProcessError(f"Copilot CLI execution failed (exit status {exc.returncode})", stdout=exc.stdout, stderr=exc.stderr, returncode=exc.returncode) from exc
    except OSError as exc:
        logger.exception("Could not start Copilot CLI")
        raise CopilotProcessError(f"Could not start Copilot CLI: {exc}") from exc
