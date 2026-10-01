from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bcbench_core.types import AgentExecution, AgentMetricsContract, DatasetEntry


@dataclass(frozen=True)
class EvaluationRequest[E: DatasetEntry]:
    entry: E
    repo_path: Path
    result_dir: Path
    result_file: str
    model: str
    prompt: str


@dataclass(frozen=True)
class EvaluationRun[E: DatasetEntry]:
    request: EvaluationRequest[E]
    agent_name: str
    agent_version: str | None
    execution: AgentExecution


class Agent[E: DatasetEntry](Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str | None: ...

    @property
    def metrics_contract(self) -> AgentMetricsContract: ...

    def run(self, request: EvaluationRequest[E]) -> AgentExecution: ...


class Workspace[E: DatasetEntry](Protocol):
    def prepare(self, entry: E, repo_path: Path) -> None: ...


class Scorer[E: DatasetEntry, R](Protocol):
    def score(self, run: EvaluationRun[E]) -> R: ...


class ResultWriter[R](Protocol):
    def write(self, result: R, output_dir: Path, filename: str) -> Path: ...


@dataclass(frozen=True)
class EvaluationFlow[E: DatasetEntry, R]:
    workspace: Workspace[E]
    scorer: Scorer[E, R]
    writer: ResultWriter[R]

    def run(self, request: EvaluationRequest[E], agent: Agent[E]) -> R:
        self.workspace.prepare(request.entry, request.repo_path)
        execution = agent.run(request)
        agent.metrics_contract.validate(execution.metrics)
        run = EvaluationRun(
            request=request,
            agent_name=agent.name,
            agent_version=agent.version,
            execution=execution,
        )
        result = self.scorer.score(run)
        self.writer.write(result, request.result_dir, request.result_file)
        return result
