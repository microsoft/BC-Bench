"""Harness-neutral contract between evaluation applications and the agents they run.

A harness wraps one way of producing an answer (a CLI agent, a review engine, a hosted agent).
Applications construct harnesses with harness-specific configuration and only use this contract,
so evaluation pipelines never depend on a concrete harness.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.metrics import AgentMetrics

__all__ = ["AgentIdentity", "AgentRequest", "AgentResult", "Harness"]


class AgentIdentity[N: str = str](BaseModel):
    """What is being evaluated, resolved before any task runs.

    ``N`` lets applications type the harness name, e.g. with their own ``StrEnum`` of harnesses.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    harness: N
    # CLI version, engine commit, or hosted agent version
    version: str
    # Configured model; None when the harness pins or delegates model selection
    model: str | None = None
    # Further pins needed to reproduce a run, e.g. a knowledge-base commit or a definition hash
    provenance: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class AgentRequest[T]:
    task: T
    # The agent's workspace: a prepared repository, or an empty directory for answer-only tasks
    work_dir: Path
    # Receives logs and raw captures
    output_dir: Path
    # None uses the harness's default
    timeout: int | None = None


@dataclass(frozen=True)
class AgentResult:
    # Final answer; None when the output is left in the workspace
    response: str | None = None
    metrics: AgentMetrics | None = None
    experiment: ExperimentConfiguration | None = None
    # Model reported by the agent, when it differs from or replaces the configured one
    observed_model: str | None = None


class Harness[T, N: str = str](Protocol):
    """Runs an agent on tasks of type ``T``, identified by a harness name of type ``N``.

    ``identity`` checks the harness is usable and raises ``AgentError`` otherwise. ``run`` raises
    ``AgentTimeoutError`` when the timeout is exceeded and ``AgentError`` for any other failure.
    """

    def identity(self) -> AgentIdentity[N]: ...

    def run(self, request: AgentRequest[T], /) -> AgentResult: ...
