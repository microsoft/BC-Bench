"""GitHub Copilot CLI Agent implementation."""

import asyncio
import contextlib
import json
import shutil
import time
from pathlib import Path

import yaml
from copilot import CopilotClient, CustomAgentConfig, MCPServerConfig

from bcbench.agent.copilot.metrics import parse_metrics_from_sdk_events
from bcbench.agent.shared import build_mcp_config, build_prompt
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import AgentAPIError, AgentError, AgentTimeoutError
from bcbench.logger import get_logger
from bcbench.operations import setup_custom_agent, setup_instructions_from_config
from bcbench.types import AgentMetrics, EvaluationCategory, ExperimentConfiguration

logger = get_logger(__name__)
_config = get_config()


def _is_api_error(error_code: str | None, error_message: str) -> bool:
    """Determine if an error is an API error (5xx, rate limit, auth) vs agent error.

    Args:
        error_code: Error code from the session error event
        error_message: Error message from the session error event

    Returns:
        True if this is an API error, False if it's an agent execution error
    """
    # Check error code for HTTP status codes
    if error_code:
        error_code_lower = error_code.lower()
        # 5xx server errors
        if error_code.startswith("5") and len(error_code) == 3 and error_code.isdigit():
            return True
        # Common API error codes
        if error_code_lower in ("rate_limit_exceeded", "unauthorized", "forbidden", "authentication_failed", "invalid_api_key", "429", "401", "403"):
            return True

    # Check error message for common API error patterns
    error_message_lower = error_message.lower()
    api_error_patterns = [
        "rate limit",
        "quota exceeded",
        "authentication",
        "unauthorized",
        "invalid api key",
        "api key",
        "server error",
        "internal server error",
        "service unavailable",
        "gateway timeout",
        "bad gateway",
        "429",
        "500",
        "502",
        "503",
        "504",
    ]

    return any(pattern in error_message_lower for pattern in api_error_patterns)


def run_copilot_agent(entry: DatasetEntry, model: str, category: EvaluationCategory, repo_path: Path, output_dir: Path, al_mcp: bool = False) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Run GitHub Copilot CLI agent on a single dataset entry.

    Returns:
        Tuple of (AgentMetrics, ExperimentConfiguration) with metrics and configuration used during the experiment
    """
    return asyncio.run(_run_copilot_agent_async(entry, model, category, repo_path, output_dir, al_mcp))


async def _run_copilot_agent_async(
    entry: DatasetEntry, model: str, category: EvaluationCategory, repo_path: Path, output_dir: Path, al_mcp: bool = False
) -> tuple[AgentMetrics | None, ExperimentConfiguration]:
    """Internal async implementation of run_copilot_agent."""
    config_file = Path(__file__).parent.parent / "shared" / "config.yaml"
    copilot_config = yaml.safe_load(config_file.read_text())

    logger.info(f"Running GitHub Copilot SDK on: {entry.instance_id}")

    prompt: str = build_prompt(entry, repo_path, copilot_config, category, al_mcp=al_mcp)
    mcp_config_json, mcp_server_names = build_mcp_config(copilot_config, entry, repo_path, al_mcp=al_mcp)
    instructions_enabled: bool = setup_instructions_from_config(copilot_config, entry, repo_path)
    custom_agent_name: str | None = setup_custom_agent(copilot_config, entry, repo_path)
    config = ExperimentConfiguration(mcp_servers=mcp_server_names, custom_instructions=instructions_enabled, custom_agent=custom_agent_name)

    logger.info(f"Executing Copilot SDK in directory: {repo_path}")
    logger.debug(f"Using prompt:\n{prompt}")

    copilot_cmd = shutil.which("copilot.cmd") or shutil.which("copilot")
    if not copilot_cmd:
        raise AgentError("Copilot CLI not found in PATH. Please ensure it is installed and available.")

    # Parse MCP config from JSON to SDK format
    mcp_servers_dict: dict[str, MCPServerConfig] | None = None
    if mcp_config_json:
        mcp_json_config = json.loads(mcp_config_json)
        mcp_servers_dict = mcp_json_config.get("mcpServers", {})

    # Build custom agent configuration if specified
    custom_agents_list: list[CustomAgentConfig] | None = None
    if custom_agent_name:
        # Custom agents are loaded from .github/agents/ directory
        # The SDK will handle loading them when we specify the agent name
        logger.debug(f"Custom agent specified: {custom_agent_name}")
        # Note: The SDK doesn't directly support custom agents via config in the same way
        # as the CLI. We'll need to handle this differently or rely on the CLI's custom
        # instructions mechanism which is already set up.
        custom_agents_list = None  # Not directly configurable in SDK session config

    # Create session configuration
    session_config = {
        "model": model,
    }

    # Add MCP servers if configured
    if mcp_servers_dict:
        session_config["mcp_servers"] = mcp_servers_dict

    # Add custom agents if configured
    if custom_agents_list:
        session_config["custom_agents"] = custom_agents_list

    # Determine available/excluded tools based on configuration
    # The CLI uses --allow-all-tools, so we don't restrict tools in the SDK
    # The CLI uses --disable-builtin-mcps, but this is default in SDK
    # The CLI uses --disable-parallel-tools-execution, but SDK doesn't expose this

    client = CopilotClient(
        {
            "cli_path": copilot_cmd,
            "cwd": str(repo_path),
            "log_level": "debug",
        }
    )

    try:
        await client.start()

        # Create session with configuration
        session = await client.create_session(session_config)

        # Track events for metrics collection
        events = []
        session_start_time = time.time()
        done = asyncio.Event()
        error_occurred = None
        error_code = None

        def on_event(event):
            nonlocal error_occurred, error_code
            events.append(event)

            # Log event for debugging
            logger.debug(f"SDK Event: {event.type.value}")

            # Check for session errors
            if event.type.value == "session.error":
                error_occurred = event.data.message
                # Extract error code if available (e.g., HTTP status codes, rate limit errors)
                if hasattr(event.data, "code") and event.data.code:
                    error_code = event.data.code
                logger.error(f"Session error: {error_occurred} (code: {error_code})")
                done.set()
            elif event.type.value == "session.idle":
                done.set()

        # Subscribe to session events
        session.on(on_event)

        # Send the prompt and wait for completion
        await session.send({"prompt": prompt})

        # Wait for session to complete or timeout
        try:
            await asyncio.wait_for(done.wait(), timeout=_config.timeout.agent_execution)
        except TimeoutError:
            logger.error(f"Copilot SDK timed out after {_config.timeout.agent_execution} seconds")
            await session.destroy()
            await client.stop()
            metrics = AgentMetrics(execution_time=_config.timeout.agent_execution)
            raise AgentTimeoutError("Copilot SDK timed out", metrics=metrics, config=config) from None

        session_end_time = time.time()
        execution_time = session_end_time - session_start_time

        # Check if an error occurred during execution
        if error_occurred:
            # Determine if this is an API error based on error code or message
            is_api_error = _is_api_error(error_code, error_occurred)
            logger.error(f"Copilot SDK execution failed with error: {error_occurred} (API error: {is_api_error})")
            await session.destroy()
            await client.stop()

            if is_api_error:
                raise AgentAPIError(f"Copilot SDK API error: {error_occurred}", error_code=error_code, metrics=None, config=config)
            raise AgentError(f"Copilot SDK execution failed: {error_occurred}")

        logger.info(f"Copilot SDK run complete for: {entry.instance_id}")

        # Parse metrics from SDK events
        metrics = parse_metrics_from_sdk_events(events, execution_time)

        # Clean up
        await session.destroy()
        await client.stop()

        return metrics, config

    except AgentTimeoutError:
        # Re-raise timeout errors as-is
        raise
    except AgentError:
        # Re-raise agent errors as-is
        raise
    except Exception as e:
        logger.exception(f"Unexpected error running Copilot SDK: {e}")
        with contextlib.suppress(Exception):
            await client.force_stop()
        raise AgentError(f"Unexpected error running Copilot SDK: {e}") from e
