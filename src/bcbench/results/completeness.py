from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, Field


class EvaluationCompleteness(BaseModel):
    expected_entry_count: int = Field(ge=0)
    produced_entry_count: int = Field(ge=0)
    missing_entry_count: int = Field(ge=0)
    unexpected_entry_count: int = Field(ge=0)
    duplicate_result_count: int = Field(ge=0)
    complete: bool

    @classmethod
    def from_instance_ids(cls, expected_entry_count: int, instance_ids: Iterable[str]) -> EvaluationCompleteness:
        ids = list(instance_ids)
        produced_entry_count = len(set(ids))
        return cls(
            expected_entry_count=expected_entry_count,
            produced_entry_count=produced_entry_count,
            missing_entry_count=max(expected_entry_count - produced_entry_count, 0),
            unexpected_entry_count=max(produced_entry_count - expected_entry_count, 0),
            duplicate_result_count=len(ids) - produced_entry_count,
            complete=produced_entry_count == expected_entry_count and len(ids) == produced_entry_count,
        )

    def to_metadata(self) -> dict[str, int | bool]:
        return {
            "expected_entry_count": self.expected_entry_count,
            "produced_entry_count": self.produced_entry_count,
            "missing_entry_count": self.missing_entry_count,
            "unexpected_entry_count": self.unexpected_entry_count,
            "duplicate_result_count": self.duplicate_result_count,
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
                "| Expected entries | Produced entries | Missing/failed entries | Unexpected entries | Duplicate results | Status |",
                "|---:|---:|---:|---:|---:|:---|",
                (f"| {self.expected_entry_count} | {self.produced_entry_count} | {self.missing_entry_count} | {self.unexpected_entry_count} | {self.duplicate_result_count} | {status} |"),
            ]
        )
