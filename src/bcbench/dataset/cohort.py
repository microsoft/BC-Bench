from __future__ import annotations

import re
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.types import DatasetTier

type CohortApplicability = Literal["8656", "8669", "8735"]
type CohortRole = Literal["target", "control"]


class EvaluationCohortEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    instance_id: str = Field(min_length=1)
    applicability: list[CohortApplicability] = Field(default_factory=list)
    role: CohortRole | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_applicability(self) -> EvaluationCohortEntry:
        if len(self.applicability) != len(set(self.applicability)):
            raise ValueError("cohort entry applicability must not contain duplicates")
        if self.notes is not None and not self.notes.strip():
            raise ValueError("cohort entry notes must be nonempty when provided")
        return self


class EvaluationCohort(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9-]*$")
    dataset: DatasetTier
    entries: list[str | EvaluationCohortEntry] = Field(min_length=1)

    @property
    def entry_ids(self) -> list[str]:
        return [entry if isinstance(entry, str) else entry.instance_id for entry in self.entries]

    def metadata_for(self, instance_id: str) -> EvaluationCohortEntry | None:
        for entry in self.entries:
            if isinstance(entry, EvaluationCohortEntry) and entry.instance_id == instance_id:
                return entry
        return None

    @model_validator(mode="after")
    def validate_entries(self) -> EvaluationCohort:
        if any(not entry_id for entry_id in self.entry_ids):
            raise ValueError("cohort entries must be nonempty instance IDs")
        if len(self.entry_ids) != len(set(self.entry_ids)):
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


def load_evaluation_cohort(path: Path, *, dataset: DatasetTier, available_entries: Sequence[BaseDatasetEntry]) -> ResolvedEvaluationCohort:
    if not path.is_file():
        raise ValueError(f"Evaluation cohort does not exist: {path}")

    raw = path.read_bytes()
    cohort = EvaluationCohort.model_validate_json(raw)
    if cohort.name != path.stem:
        raise ValueError(f"Evaluation cohort name {cohort.name!r} must match filename {path.stem!r}")
    if cohort.dataset != dataset:
        raise ValueError(f"Evaluation cohort {cohort.name!r} targets dataset {cohort.dataset.value!r}, not {dataset.value!r}")

    available_ids = {entry.instance_id for entry in available_entries}
    missing = [entry_id for entry_id in cohort.entry_ids if entry_id not in available_ids]
    if missing:
        raise ValueError(f"Evaluation cohort {cohort.name!r} contains unknown instance IDs: {missing}")

    return ResolvedEvaluationCohort(cohort=cohort, sha256=sha256(raw).hexdigest())
