from __future__ import annotations

import re
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.types import DatasetTier


class EvaluationCohort(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    tier: DatasetTier
    entries: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entries(self) -> EvaluationCohort:
        if any(not entry_id for entry_id in self.entries):
            raise ValueError("cohort entries must be nonempty instance IDs")
        if len(self.entries) != len(set(self.entries)):
            raise ValueError("cohort entries must not contain duplicates")
        return self


class ResolvedEvaluationCohort(BaseModel):
    model_config = ConfigDict(frozen=True)

    cohort: EvaluationCohort
    sha256: str


def evaluation_cohort_path(cohort_dir: Path, name: str) -> Path:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) is None:
        raise ValueError(f"Invalid evaluation cohort name: {name!r}")
    return cohort_dir / f"{name}.json"


def load_evaluation_cohort(path: Path, *, tier: DatasetTier, available_entries: Sequence[BaseDatasetEntry]) -> ResolvedEvaluationCohort:
    if not path.is_file():
        raise ValueError(f"Evaluation cohort does not exist: {path}")

    raw = path.read_bytes()
    cohort = EvaluationCohort.model_validate_json(raw)
    if cohort.name != path.stem:
        raise ValueError(f"Evaluation cohort name {cohort.name!r} must match filename {path.stem!r}")
    if cohort.tier != tier:
        raise ValueError(f"Evaluation cohort {cohort.name!r} targets tier {cohort.tier.value!r}, not {tier.value!r}")

    available_ids = {entry.instance_id for entry in available_entries}
    missing = [entry_id for entry_id in cohort.entries if entry_id not in available_ids]
    if missing:
        raise ValueError(f"Evaluation cohort {cohort.name!r} contains unknown instance IDs: {missing}")

    return ResolvedEvaluationCohort(cohort=cohort, sha256=sha256(raw).hexdigest())
