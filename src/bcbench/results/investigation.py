from collections.abc import Sequence
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from bcbench.dataset import RepoGroundedEntry
from bcbench.logger import get_logger
from bcbench.patch import extract_file_paths_from_patch
from bcbench.results.base import ExecutionBasedEvaluationResult
from bcbench.types import EvaluationContext, InvestigationTrace

logger = get_logger(__name__)


def _path_keys(paths: Sequence[str]) -> set[str]:
    return {path.replace("\\", "/").casefold() for path in paths}


def _different_paths(paths: Sequence[str], excluded: set[str]) -> list[str]:
    return sorted({path.replace("\\", "/").casefold(): path.replace("\\", "/") for path in paths if path.replace("\\", "/").casefold() not in excluded}.values())


class InvestigationMeasurement(BaseModel):
    model_config = ConfigDict(frozen=True)

    trace: InvestigationTrace
    reference_source_files: list[str]
    reference_output_files: list[str]
    modified_files: list[str] | None = None

    @computed_field
    @property
    def scope_complete(self) -> bool:
        return self.trace.initial_scope is not None and self.trace.final_scope is not None

    @computed_field
    @property
    def added_scope_files(self) -> list[str] | None:
        if self.trace.initial_scope is None or self.trace.final_scope is None:
            return None
        initial = _path_keys(self.trace.initial_scope.files)
        return _different_paths(self.trace.final_scope.files, initial)

    @computed_field
    @property
    def initial_reference_recall(self) -> float | None:
        reference = _path_keys(self.reference_source_files)
        if self.trace.initial_scope is None or not reference:
            return None
        return len(_path_keys(self.trace.initial_scope.files) & reference) / len(reference)

    @computed_field
    @property
    def final_reference_recall(self) -> float | None:
        reference = _path_keys(self.reference_source_files)
        if self.trace.final_scope is None or not reference:
            return None
        return len(_path_keys(self.trace.final_scope.files) & reference) / len(reference)

    @computed_field
    @property
    def reference_recall_gain(self) -> float | None:
        before, after = self.initial_reference_recall, self.final_reference_recall
        return after - before if before is not None and after is not None else None

    @computed_field
    @property
    def new_reference_files(self) -> list[str] | None:
        if self.added_scope_files is None:
            return None
        added = _path_keys(self.added_scope_files)
        return _different_paths(self.reference_source_files, _path_keys(self.reference_source_files) - added)

    @computed_field
    @property
    def modified_outside_reference(self) -> list[str] | None:
        if self.modified_files is None:
            return None
        reference = _path_keys(self.reference_output_files)
        return _different_paths(self.modified_files, reference)

    @property
    def measurements(self) -> dict[str, int | float | bool]:
        values: dict[str, int | float | bool] = {
            "scope_complete": self.scope_complete,
            "history_queries": len(self.trace.queries),
            "history_errors": sum(query.error is not None for query in self.trace.queries),
            "history_seconds": sum(query.elapsed_seconds for query in self.trace.queries),
            "history_returned_queries": sum(query.error is None and bool(query.commit_ids) for query in self.trace.queries),
            "scope_reference_source_files": len(_path_keys(self.reference_source_files)),
            "scope_reference_output_files": len(_path_keys(self.reference_output_files)),
        }
        for label, snapshot in (("initial", self.trace.initial_scope), ("final", self.trace.final_scope)):
            if snapshot is not None:
                values[f"scope_{label}_files"] = len(_path_keys(snapshot.files))
        if self.added_scope_files is not None:
            values["scope_added_files"] = len(self.added_scope_files)
        if self.new_reference_files is not None:
            values["scope_new_reference_files"] = len(self.new_reference_files)
        for label, recall in (("initial", self.initial_reference_recall), ("final", self.final_reference_recall), ("gain", self.reference_recall_gain)):
            if recall is not None:
                values[f"scope_reference_recall_{label}"] = recall
        if self.modified_files is not None:
            values["scope_modified_files"] = len(_path_keys(self.modified_files))
        if self.modified_outside_reference is not None:
            values["scope_modified_outside_reference"] = len(self.modified_outside_reference)
        return values


class InvestigatedExecutionResult(ExecutionBasedEvaluationResult):
    investigation: InvestigationMeasurement | None = Field(default=None, exclude_if=lambda value: value is None)

    @classmethod
    def _base_fields(cls, context: EvaluationContext) -> dict[str, Any]:
        fields = super()._base_fields(context)
        trace = context.metrics.investigation if context.metrics else None
        if trace is not None:
            if not isinstance(context.entry, RepoGroundedEntry):
                raise TypeError("Scope measurements require a repository-grounded entry")
            expected_output = context.entry.get_expected_output()
            if not isinstance(expected_output, str):
                raise TypeError("Scope measurements require a patch-style expected output")
            fields["investigation"] = InvestigationMeasurement(
                trace=trace,
                reference_source_files=extract_file_paths_from_patch(context.entry.patch),
                reference_output_files=extract_file_paths_from_patch(expected_output),
            )
            if trace.initial_scope is None or trace.final_scope is None:
                logger.warning("Scope snapshots are incomplete for %s; paired discovery measurements are unavailable", context.entry.instance_id)
        return fields

    @model_validator(mode="after")
    def capture_modified_files(self) -> Self:
        if self.investigation is not None:
            modified_files = None if self.timeout else extract_file_paths_from_patch(self.output)
            self.investigation = self.investigation.model_copy(update={"modified_files": modified_files})
        return self

    @property
    def category_metrics(self) -> dict[str, int | float | bool]:
        return {**super().category_metrics, **(self.investigation.measurements if self.investigation else {})}

    @property
    def display_row(self) -> dict[str, str]:
        if self.investigation is None:
            return super().display_row
        added = self.investigation.added_scope_files
        return {
            **super().display_row,
            "History Queries": str(len(self.investigation.trace.queries)),
            "Scope Complete": "Yes" if self.investigation.scope_complete else "No",
            "Scope Files Added": str(len(added)) if added is not None else "N/A",
        }


class InvestigationSummary(BaseModel):
    attempts: int = 0
    complete_scope_attempts: int = 0
    history_used_attempts: int = 0
    history_returned_attempts: int = 0
    history_queries: int = 0
    history_errors: int = 0
    history_seconds: float = 0.0
    paired_reference_attempts: int = 0
    initial_reference_recall_sum: float = 0.0
    final_reference_recall_sum: float = 0.0
    new_reference_files_sum: int = 0
    modified_scope_attempts: int = 0
    modified_files_sum: int = 0
    modified_outside_reference_sum: int = 0

    @computed_field
    @property
    def average_initial_reference_recall(self) -> float | None:
        return self.initial_reference_recall_sum / self.paired_reference_attempts if self.paired_reference_attempts else None

    @computed_field
    @property
    def average_final_reference_recall(self) -> float | None:
        return self.final_reference_recall_sum / self.paired_reference_attempts if self.paired_reference_attempts else None

    @computed_field
    @property
    def average_reference_recall_gain(self) -> float | None:
        return (self.final_reference_recall_sum - self.initial_reference_recall_sum) / self.paired_reference_attempts if self.paired_reference_attempts else None

    @computed_field
    @property
    def average_new_reference_files(self) -> float | None:
        return self.new_reference_files_sum / self.paired_reference_attempts if self.paired_reference_attempts else None

    @computed_field
    @property
    def average_history_seconds(self) -> float:
        return self.history_seconds / self.attempts if self.attempts else 0.0

    @computed_field
    @property
    def average_modified_outside_reference(self) -> float | None:
        return self.modified_outside_reference_sum / self.modified_scope_attempts if self.modified_scope_attempts else None

    @classmethod
    def from_measurements(cls, measurements: Sequence[InvestigationMeasurement]) -> Self | None:
        if not measurements:
            return None
        summary = cls(attempts=len(measurements))
        for measurement in measurements:
            summary.complete_scope_attempts += int(measurement.scope_complete)
            summary.history_used_attempts += int(bool(measurement.trace.queries))
            summary.history_returned_attempts += int(any(query.error is None and query.commit_ids for query in measurement.trace.queries))
            summary.history_queries += len(measurement.trace.queries)
            summary.history_errors += sum(query.error is not None for query in measurement.trace.queries)
            summary.history_seconds += sum(query.elapsed_seconds for query in measurement.trace.queries)
            before, after = measurement.initial_reference_recall, measurement.final_reference_recall
            if before is not None and after is not None:
                summary.paired_reference_attempts += 1
                summary.initial_reference_recall_sum += before
                summary.final_reference_recall_sum += after
                summary.new_reference_files_sum += len(measurement.new_reference_files or [])
            if measurement.modified_files is not None:
                summary.modified_scope_attempts += 1
                summary.modified_files_sum += len(_path_keys(measurement.modified_files))
                summary.modified_outside_reference_sum += len(measurement.modified_outside_reference or [])
        return summary

    @classmethod
    def combine(cls, summaries: Sequence["InvestigationSummary"]) -> Self | None:
        if not summaries:
            return None
        return cls.model_validate({name: sum(getattr(summary, name) for summary in summaries) for name in cls.model_fields})

    def render_markdown(self) -> str:
        before, after = self.average_initial_reference_recall, self.average_final_reference_recall
        recall = f"{before:.1%} -> {after:.1%}" if before is not None and after is not None else "Unavailable"
        return (
            "## Scope discovery (agent-reported file scope)\n"
            f"- Complete scope snapshots: {self.complete_scope_attempts}/{self.attempts}\n"
            f"- Attempts requesting / receiving nonempty history: {self.history_used_attempts} / {self.history_returned_attempts} (of {self.attempts})\n"
            f"- History queries / errors: {self.history_queries} / {self.history_errors}\n"
            f"- Average history time: {self.average_history_seconds:.1f}s\n"
            f"- Reference source-file recall, before -> after: {recall} ({self.paired_reference_attempts} paired attempts)\n"
            "- Reference overlap is a file-based proxy, not a correctness score or proof of source inspection.\n"
        )
