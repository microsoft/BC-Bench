from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict

from bcbench.results.base import JudgeScoredEvaluationResult
from bcbench.types import EvaluationContext


def _metadata_scalar(value: object) -> str | int | float | bool | None:
    return value if isinstance(value, str | int | float | bool) else None


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
    execution_identity: dict[str, object] | None = None
    workspace_seed: dict[str, object] | None = None
    prompt_evidence: dict[str, object] | None = None
    canonical_trace: dict[str, object] | None = None

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
        execution_identity: dict[str, object] | None = None,
        workspace_seed: dict[str, object] | None = None,
        prompt_evidence: dict[str, object] | None = None,
        canonical_trace: dict[str, object] | None = None,
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
            execution_identity=execution_identity,
            workspace_seed=workspace_seed,
            prompt_evidence=prompt_evidence,
            canonical_trace=canonical_trace,
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
        execution_identity = self.execution_identity or {}
        workspace_seed = self.workspace_seed or {}
        prompt_evidence = self.prompt_evidence or {}
        canonical_trace = self.canonical_trace or {}
        compositions = prompt_evidence.get("compositions")
        uses = prompt_evidence.get("uses")
        events = canonical_trace.get("events")
        metadata: dict[str, str | int | float | bool | None] = {key: _metadata_scalar(value) for key, value in super().export_metadata.items()}
        metadata["independent_build_status"] = self.independent_build.status
        metadata["runtime_status"] = self.runtime_status
        metadata["harness_failure"] = self.harness_failure
        metadata["bcal_product_version"] = _metadata_scalar(execution_identity.get("productVersion"))
        metadata["bcal_source_commit_sha"] = _metadata_scalar(execution_identity.get("sourceCommitSha"))
        metadata["bcal_evidence_contract_version"] = _metadata_scalar(execution_identity.get("evidenceContractVersion"))
        metadata["workspace_seed_contract_version"] = _metadata_scalar(workspace_seed.get("contractVersion"))
        metadata["workspace_seed_file_count"] = _metadata_scalar(workspace_seed.get("fileCount"))
        metadata["workspace_seed_aggregate_bytes"] = _metadata_scalar(workspace_seed.get("aggregateBytes"))
        metadata["workspace_seed_aggregate_sha256"] = _metadata_scalar(workspace_seed.get("aggregateSha256"))
        metadata["prompt_composition_count"] = len(compositions) if isinstance(compositions, list) else None
        metadata["prompt_use_count"] = len(uses) if isinstance(uses, list) else None
        metadata["canonical_trace_event_count"] = len(events) if isinstance(events, list) else None
        metadata["canonical_trace_truncated"] = _metadata_scalar(canonical_trace.get("truncated"))
        metadata["canonical_trace_omitted_event_count"] = _metadata_scalar(canonical_trace.get("omittedEventCount"))
        return metadata
