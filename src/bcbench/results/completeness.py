from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field


class EvaluationCompleteness(BaseModel):
    expected_entry_count: int = Field(ge=0)
    produced_entry_count: int = Field(ge=0)
    missing_entry_count: int = Field(ge=0)
    unexpected_entry_count: int = Field(ge=0)
    duplicate_result_count: int = Field(ge=0)
    infrastructure_failure_count: int = Field(ge=0)
    missing_instance_ids: list[str] = Field(default_factory=list)
    unexpected_instance_ids: list[str] = Field(default_factory=list)
    duplicate_instance_ids: list[str] = Field(default_factory=list)
    infrastructure_failure_instance_ids: list[str] = Field(default_factory=list)
    complete: bool

    @classmethod
    def from_instance_ids(
        cls,
        expected_entry_count: int,
        instance_ids: Iterable[str],
        *,
        expected_instance_ids: Iterable[str] | None = None,
        infrastructure_failure_instance_ids: Iterable[str] = (),
    ) -> EvaluationCompleteness:
        ids = list(instance_ids)
        counts = Counter(ids)
        produced_ids = set(counts)
        produced_entry_count = len(produced_ids)
        duplicate_instance_ids = sorted(instance_id for instance_id, count in counts.items() if count > 1)
        duplicate_result_count = sum(count - 1 for count in counts.values())

        if expected_instance_ids is None:
            missing_instance_ids: list[str] = []
            unexpected_instance_ids: list[str] = []
            missing_entry_count = max(expected_entry_count - produced_entry_count, 0)
            unexpected_entry_count = max(produced_entry_count - expected_entry_count, 0)
        else:
            expected_ids = list(expected_instance_ids)
            expected_set = set(expected_ids)
            if len(expected_set) != len(expected_ids):
                raise ValueError("Expected instance IDs must be unique.")
            if len(expected_ids) != expected_entry_count:
                raise ValueError(f"Expected entry count {expected_entry_count} does not match {len(expected_ids)} expected instance IDs.")

            missing_instance_ids = sorted(expected_set - produced_ids)
            unexpected_instance_ids = sorted(produced_ids - expected_set)
            missing_entry_count = len(missing_instance_ids)
            unexpected_entry_count = len(unexpected_instance_ids)

        infrastructure_ids = sorted(set(infrastructure_failure_instance_ids))
        complete = missing_entry_count == 0 and unexpected_entry_count == 0 and duplicate_result_count == 0
        return cls(
            expected_entry_count=expected_entry_count,
            produced_entry_count=produced_entry_count,
            missing_entry_count=missing_entry_count,
            unexpected_entry_count=unexpected_entry_count,
            duplicate_result_count=duplicate_result_count,
            infrastructure_failure_count=len(infrastructure_ids),
            missing_instance_ids=missing_instance_ids,
            unexpected_instance_ids=unexpected_instance_ids,
            duplicate_instance_ids=duplicate_instance_ids,
            infrastructure_failure_instance_ids=infrastructure_ids,
            complete=complete,
        )

    def to_metadata(self) -> dict[str, int | bool]:
        return {
            "expected_entry_count": self.expected_entry_count,
            "produced_entry_count": self.produced_entry_count,
            "missing_entry_count": self.missing_entry_count,
            "unexpected_entry_count": self.unexpected_entry_count,
            "duplicate_result_count": self.duplicate_result_count,
            "infrastructure_failure_count": self.infrastructure_failure_count,
            "evaluation_complete": self.complete,
        }

    def save(self, output_file: Path) -> None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, input_file: Path) -> EvaluationCompleteness:
        return cls.model_validate(json.loads(input_file.read_text(encoding="utf-8")))

    def render_markdown(self) -> str:
        status = ":white_check_mark: Complete" if self.complete else ":x: Incomplete"
        return "\n".join(
            [
                "## Evaluation completeness",
                "",
                "| Expected entries | Produced entries | Missing entries | Infrastructure failures | Unexpected entries | Duplicate results | Status |",
                "|---:|---:|---:|---:|---:|---:|:---|",
                (
                    f"| {self.expected_entry_count} | {self.produced_entry_count} | {self.missing_entry_count} | "
                    f"{self.infrastructure_failure_count} | {self.unexpected_entry_count} | {self.duplicate_result_count} | {status} |"
                ),
            ]
        )
