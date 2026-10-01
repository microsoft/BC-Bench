from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

from bcbench.results.base import JudgeScoredEvaluationResult
from bcbench.types import EvaluationContext


class IndependentBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["passed", "failed", "not_attempted"]
    message: str | None = None

    @property
    def passed(self) -> bool:
        return self.status == "passed"


class TraceAssertionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    assertion_id: str
    passed: bool
    message: str


class BCalScenarioEvaluationResult(JudgeScoredEvaluationResult):
    scenario_completed: bool = False
    independent_build: IndependentBuildResult
    trace_compliance: bool = False
    trace_assertions: list[TraceAssertionResult]
    runtime_status: Literal["passed", "failed", "not_run"] | None = None
    harness_failure: bool = False

    @classmethod
    def create_agent_timeout_failure(cls, context: EvaluationContext) -> Self:
        return cls(
            **cls._base_fields(context),
            timeout=True,
            error_message="Agent timed out",
            independent_build=IndependentBuildResult(status="not_attempted", message="Agent timed out before evaluation"),
            trace_assertions=[],
        )

    @classmethod
    def create(
        cls,
        context: EvaluationContext,
        *,
        output: str,
        scenario_completed: bool,
        independent_build: IndependentBuildResult,
        trace_assertions: list[TraceAssertionResult],
        runtime_status: Literal["passed", "failed", "not_run"] | None,
        error_message: str | None = None,
    ) -> Self:
        return cls(
            **cls._base_fields(context),
            output=output,
            error_message=error_message,
            scenario_completed=scenario_completed,
            independent_build=independent_build,
            trace_compliance=all(assertion.passed for assertion in trace_assertions),
            trace_assertions=trace_assertions,
            runtime_status=runtime_status,
        )

    @property
    def status_label(self) -> str:
        if self.timeout:
            return "Timeout"
        if self.harness_failure:
            return "Harness error"
        if self.scenario_completed and self.trace_compliance and self.independent_build.status != "failed":
            return "Unscored"
        return "Failed"

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        metrics: dict[str, int | float | bool] = {
            "scenario_completed": self.scenario_completed,
            "independent_build": self.independent_build.passed,
            "independent_build_attempted": self.independent_build.status != "not_attempted",
            "trace_compliance": self.trace_compliance,
        }
        if self.runtime_status is not None:
            metrics["runtime_verified"] = self.runtime_status == "passed"
            metrics["runtime_attempted"] = self.runtime_status != "not_run"
        return metrics

    @property
    def export_metadata(self) -> dict[str, str | int | float | bool | None]:
        return {
            **super().export_metadata,
            "independent_build_status": self.independent_build.status,
            "runtime_status": self.runtime_status,
            "harness_failure": self.harness_failure,
        }
