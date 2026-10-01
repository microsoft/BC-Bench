from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AgentMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["generic"] = "generic"
    execution_time: float | None = None
    llm_duration: float | None = None
    ai_credits: float | None = None
    turn_count: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    tool_usage: dict[str, int] | None = None


@dataclass(frozen=True)
class AgentMetricsContract:
    metrics_type: type[AgentMetrics]
    required_fields: frozenset[str]

    def __post_init__(self) -> None:
        if unknown_fields := self.required_fields - self.metrics_type.model_fields.keys():
            raise ValueError(f"{self.metrics_type.__name__} does not define required fields: {sorted(unknown_fields)}")
