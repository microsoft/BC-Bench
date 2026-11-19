"""Metrics reported by coding agents."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class AgentMetrics(BaseModel):
    """Metrics collected during agent execution.

    Separates runtime execution data from experiment configuration.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["generic"] = "generic"

    # Total execution time in seconds
    execution_time: float | None = None
    llm_duration: float | None = None

    # Session cost in AI Credits (GitHub Copilot only)
    ai_credits: float | None = None

    turn_count: int | None = None

    # Token usage from LLM calls
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    total_tokens: int | None = None

    # Tool usage statistics from agent logs
    tool_usage: dict[str, int] | None = None
