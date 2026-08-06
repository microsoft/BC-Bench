"""Agent module for BC-Bench."""

from bcbench.agent.bcal import BCAL_EXPECTED_METRICS, BCalBackendConfig, run_bcal_agent
from bcbench.agent.claude import CLAUDE_EXPECTED_METRICS, run_claude_code
from bcbench.agent.copilot import COPILOT_EXPECTED_METRICS, run_copilot_agent

__all__ = [
    "BCAL_EXPECTED_METRICS",
    "CLAUDE_EXPECTED_METRICS",
    "COPILOT_EXPECTED_METRICS",
    "BCalBackendConfig",
    "run_bcal_agent",
    "run_claude_code",
    "run_copilot_agent",
]
