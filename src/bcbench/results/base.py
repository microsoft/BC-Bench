"""Base evaluation result class with shared metrics across all evaluation categories."""

import json
import logging
from pathlib import Path
from typing import Any, Literal, Self, cast, override

from pydantic import BaseModel, model_validator

from bcbench.dataset import BaseDatasetEntry
from bcbench.types import AnyAgentMetrics, DatasetTier, EvaluationCategory, EvaluationContext, ExperimentConfiguration

logger = logging.getLogger(__name__)


class BaseEvaluationResult(BaseModel):
    """Base class for all evaluation results with shared metrics across categories."""

    instance_id: str
    project: str
    model: str
    agent_name: str
    category: EvaluationCategory
    tier: DatasetTier = DatasetTier.GOLD
    agent_version: str | None = None

    timeout: bool = False

    output: str = ""
    error_message: str | None = None

    metrics: AnyAgentMetrics | None = None
    experiment: ExperimentConfiguration | None = None
    cohort_name: str | None = None
    cohort_sha256: str | None = None
    cohort_applicability: list[str] | None = None
    cohort_role: Literal["target", "control"] | None = None
    cohort_notes: str | None = None
    repetition_index: int | None = None
    repetition_count: int | None = None
    study_id: str | None = None
    variant_id: str | None = None
    bcal_common_base_sha: str | None = None
    bcal_variant_patch_sha: str | None = None

    @classmethod
    def _base_fields[E: BaseDatasetEntry](cls, context: EvaluationContext[E]) -> dict[str, Any]:
        metrics_contract = context.agent_name.metrics_contract
        if not context.metrics:
            logger.warning(f"Creating result for {context.entry.instance_id} with no agent metrics - performance data will be unavailable")
        elif type(context.metrics) is not metrics_contract.metrics_type:
            raise TypeError(f"{context.agent_name} must use {metrics_contract.metrics_type.__name__}, got {type(context.metrics).__name__}")
        elif missing_metrics := sorted(name for name in metrics_contract.required_fields if getattr(context.metrics, name) is None):
            logger.warning(f"Result for {context.entry.instance_id} missing metrics: {', '.join(missing_metrics)}")

        return {
            "instance_id": context.entry.instance_id,
            "project": context.entry.extract_project_name(),
            "model": context.model.replace(".", "-"),
            "category": context.category,
            "tier": context.tier,
            "agent_name": context.agent_name,
            "agent_version": context.agent_version,
            "metrics": context.metrics,
            "experiment": context.experiment,
            "cohort_name": context.cohort_name,
            "cohort_sha256": context.cohort_sha256,
            "cohort_applicability": context.cohort_applicability,
            "cohort_role": context.cohort_role,
            "cohort_notes": context.cohort_notes,
            "repetition_index": context.repetition_index,
            "repetition_count": context.repetition_count,
            "study_id": context.study_id,
            "variant_id": context.variant_id,
            "bcal_common_base_sha": context.bcal_common_base_sha,
            "bcal_variant_patch_sha": context.bcal_variant_patch_sha,
        }

    @model_validator(mode="after")
    def validate_study_metadata(self) -> Self:
        if (self.cohort_name is None) != (self.cohort_sha256 is None):
            raise ValueError("cohort name and SHA-256 must be provided together")
        if (self.repetition_index is None) != (self.repetition_count is None):
            raise ValueError("repetition index and repetition count must be provided together")
        if self.repetition_index is not None and self.repetition_count is not None and (self.repetition_count < 1 or not 1 <= self.repetition_index <= self.repetition_count):
            raise ValueError("repetition index must be between 1 and repetition count")
        if self.cohort_name is not None and self.repetition_index is None:
            raise ValueError("cohort results must record repetition metadata")

        study_values = (self.study_id, self.variant_id, self.bcal_common_base_sha, self.bcal_variant_patch_sha)
        if any(value is not None for value in study_values) and any(value is None for value in study_values):
            raise ValueError("study ID, variant ID, BCal common base SHA, and BCal variant patch SHA must be provided together")
        if any(value is not None and not value.strip() for value in study_values):
            raise ValueError("study metadata values must be nonempty")
        return self

    @classmethod
    def create_agent_timeout_failure[E: BaseDatasetEntry](cls, context: EvaluationContext[E]) -> Self:
        return cls(**cls._base_fields(context), timeout=True, error_message="Agent timed out")

    def save(self, output_dir: Path, result_file: str) -> None:
        output_file = output_dir / result_file
        output_dir.mkdir(parents=True, exist_ok=True)
        with output_file.open("a", encoding="utf-8") as f:
            result_dict = self.model_dump(mode="json")
            # Per-instance JSONL result files are uploaded as workflow artifacts and are the only inputs required by the summarize-results workflow.
            f.write(json.dumps(result_dict) + "\n")

        logger.info(f"Saved evaluation result for {self.instance_id} to {output_file}")

    @property
    def status_label(self) -> str:
        """Short human-readable label for the result status shown in tables (e.g. 'Completed', 'Timeout')."""
        if self.timeout:
            return "Timeout"
        if self.error_message:
            return "Error"
        return "Completed"

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        """Category-specific metrics included in bceval export metadata.

        Keys become metadata fields; values must be JSON-serializable scalars.
        Subclasses override to add metrics like 'resolved', 'build', etc.
        """
        return {}

    @property
    def export_metadata(self) -> dict[str, Any]:
        """Extra metadata fields for the bceval export beyond the shared ones.

        Subclasses override to record category-specific provenance such as the judge model.
        """
        metadata = {
            "cohort_name": self.cohort_name,
            "cohort_sha256": self.cohort_sha256,
            "cohort_applicability": self.cohort_applicability,
            "cohort_role": self.cohort_role,
            "cohort_notes": self.cohort_notes,
            "repetition_index": self.repetition_index,
            "repetition_count": self.repetition_count,
            "study_id": self.study_id,
            "variant_id": self.variant_id,
            "bcal_common_base_sha": self.bcal_common_base_sha,
            "bcal_variant_patch_sha": self.bcal_variant_patch_sha,
        }
        return {key: value for key, value in metadata.items() if value is not None}

    @property
    def display_row(self) -> dict[str, str]:
        """Extra columns for per-instance detail tables.

        Keys are column headers; values are the cell text for this result.
        Subclasses override to surface category-specific per-instance info.
        """
        return {}

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "BaseEvaluationResult":
        category = EvaluationCategory(payload["category"])
        return category.result_class.model_validate(payload)


class ExecutionBasedEvaluationResult(BaseEvaluationResult):
    """Result for categories that involve building/compiling AL code and have binary pass/fail outcomes."""

    resolved: bool = False
    build: bool = False

    @classmethod
    def create_success[E: BaseDatasetEntry](cls, context: EvaluationContext[E], output: str) -> Self:
        return cls(**cls._base_fields(context), output=output, resolved=True, build=True)

    @classmethod
    def create_build_failure[E: BaseDatasetEntry](cls, context: EvaluationContext[E], output: str, error_message: str) -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message, resolved=False, build=False)

    @classmethod
    def create_result[E: BaseDatasetEntry](cls, context: EvaluationContext[E], output: str, *, build: bool, resolved: bool, error_message: str | None = None) -> Self:
        """General factory for execution outcomes, e.g. compiled+ran but produced the wrong result (build=True, resolved=False)."""
        return cls(**cls._base_fields(context), output=output, build=build, resolved=resolved, error_message=error_message)

    @property
    @override
    def status_label(self) -> str:
        if self.timeout:
            return "Timeout"
        return "Success" if self.resolved else "Failed"

    @property
    @override
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {"resolved": self.resolved, "build": self.build}


class JudgeScoredEvaluationResult(BaseEvaluationResult):
    """Result for categories whose scoring involves an LLM judge, recording which judge model was pinned for the run."""

    judge_model: str

    @model_validator(mode="before")
    @classmethod
    def restore_missing_timeout_judge_model(cls, payload: object) -> object:
        if not isinstance(payload, dict):
            return payload

        payload = cast(dict[str, object], payload)
        if payload.get("timeout") is not True or "judge_model" in payload:
            return payload

        category = EvaluationCategory(payload["category"])
        if (judge_model := category.judge_model) is None:
            return payload

        return {**payload, "judge_model": judge_model}

    @classmethod
    @override
    def _base_fields[E: BaseDatasetEntry](cls, context: EvaluationContext[E]) -> dict[str, Any]:
        return {**super()._base_fields(context), "judge_model": context.category.judge_model}

    @property
    @override
    def export_metadata(self) -> dict[str, Any]:
        return {**super().export_metadata, "judge_model": self.judge_model}


class JudgeBasedEvaluationResult(JudgeScoredEvaluationResult):
    """Result for categories scored by LLM-as-judge (e.g. lm_checklist).

    The local pipeline only persists the agent's raw output; actual scoring is performed downstream by bceval
    and lives in the external scoring backend (e.g. Kusto) not in these local artifacts.
    """

    @classmethod
    def create_raw[E: BaseDatasetEntry](cls, context: EvaluationContext[E], output: str) -> Self:
        return cls(**cls._base_fields(context), output=output)

    @classmethod
    def create_failure[E: BaseDatasetEntry](cls, context: EvaluationContext[E], output: str, error_message: str) -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message)

    @classmethod
    def create_empty_output[E: BaseDatasetEntry](cls, context: EvaluationContext[E]) -> Self:
        return cls(**cls._base_fields(context), output="")

    @property
    @override
    def status_label(self) -> str:
        if self.timeout:
            return "Timeout"
        if self.error_message:
            return "Error"
        return "Unscored"
