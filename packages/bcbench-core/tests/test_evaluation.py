from dataclasses import dataclass, field
from pathlib import Path

import pytest

from bcbench_core.agent.experiment import ExperimentConfiguration
from bcbench_core.agent.harness import AgentIdentity, AgentRequest, AgentResult
from bcbench_core.agent.metrics import AgentMetrics
from bcbench_core.evaluation import evaluate_task
from bcbench_core.exceptions import AgentError, AgentTimeoutError

AGENT = AgentIdentity(harness="stub", version="1.0")


@dataclass
class RecordingCategory:
    calls: list[str] = field(default_factory=list)
    results: list[AgentResult] = field(default_factory=list)

    def prepare_workspace(self, task: str) -> None:
        self.calls.append("prepare_workspace")

    def prepare(self, task: str) -> None:
        self.calls.append("prepare")

    def grade(self, task: str, result: AgentResult) -> str:
        self.calls.append("grade")
        self.results.append(result)
        return f"graded {task}"


@dataclass
class StubHarness:
    result: AgentResult | None = None
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)
    category: RecordingCategory | None = None

    def identity(self) -> AgentIdentity:
        return AGENT

    def run(self, request: AgentRequest[str], /) -> AgentResult:
        if self.category is not None:
            self.category.calls.append("run")
        if self.error is not None:
            raise self.error
        return self.result or AgentResult()


def _timed_out(task: str, observed: AgentResult) -> str:
    raise AssertionError(f"{task} must not time out")


def _request(tmp_path: Path) -> AgentRequest[str]:
    return AgentRequest(task="prompt", work_dir=tmp_path, output_dir=tmp_path / "logs")


def test_prepares_runs_then_grades_the_agent_result(tmp_path: Path):
    category = RecordingCategory()
    result = AgentResult(metrics=AgentMetrics(execution_time=1.0), experiment=ExperimentConfiguration(custom_instructions=True), transcript={"trace": []})
    harness = StubHarness(result=result, category=category)

    graded = evaluate_task(category, "task-1", harness, _request(tmp_path), on_timeout=_timed_out)

    assert graded == "graded task-1"
    assert category.calls == ["prepare", "run", "grade"]
    assert category.results == [result]


def test_timeout_skips_grading_and_keeps_what_was_observed(tmp_path: Path):
    category = RecordingCategory()
    metrics = AgentMetrics(execution_time=600.0)
    config = ExperimentConfiguration(custom_instructions=True)
    harness = StubHarness(error=AgentTimeoutError("too slow", metrics=metrics, config=config, transcript={"trace": []}), category=category)

    observed: list[tuple[str, AgentResult]] = []

    def on_timeout(task: str, result: AgentResult) -> str:
        observed.append((task, result))
        return "timed out"

    graded = evaluate_task(category, "task-1", harness, _request(tmp_path), on_timeout=on_timeout)

    assert graded == "timed out"
    assert category.calls == ["prepare", "run"]
    assert observed == [("task-1", AgentResult(metrics=metrics, experiment=config, transcript={"trace": []}))]


def test_agent_errors_propagate_without_grading(tmp_path: Path):
    category = RecordingCategory()
    harness = StubHarness(error=AgentError("agent failed"), category=category)

    with pytest.raises(AgentError, match="agent failed"):
        evaluate_task(category, "task-1", harness, _request(tmp_path), on_timeout=_timed_out)

    assert category.calls == ["prepare", "run"]
