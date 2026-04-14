"""Family-level evaluation data models.

The primary analysis unit is the family, not the individual instance.
Family members (base + CFs) are correlated samples sharing the same task
skeleton — they are NOT independent IID samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bcbench.types import FailureLayer


class FamilyType(str, Enum):
    STABLE_CORRECT = "stable-correct"
    FRAGILE = "fragile"
    UNSOLVED = "unsolved"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True)
class InstanceResult:
    instance_id: str
    is_base: bool
    compiled: bool
    passed: bool


@dataclass(frozen=True)
class FamilyOutcome:
    family_id: str
    failure_layer: FailureLayer | None
    base: InstanceResult
    cfs: tuple[InstanceResult, ...]

    @property
    def pattern(self) -> tuple[int, ...]:
        return (int(self.base.passed), *(int(cf.passed) for cf in self.cfs))

    @property
    def family_type(self) -> FamilyType:
        if self.base.passed and all(cf.passed for cf in self.cfs):
            return FamilyType.STABLE_CORRECT
        if self.base.passed and any(not cf.passed for cf in self.cfs):
            return FamilyType.FRAGILE
        if not self.base.passed and any(cf.passed for cf in self.cfs):
            return FamilyType.INCONSISTENT
        return FamilyType.UNSOLVED

    @property
    def is_fragile(self) -> bool:
        return self.family_type == FamilyType.FRAGILE

    @property
    def cf_fail_count(self) -> int:
        return sum(1 for cf in self.cfs if not cf.passed)

    @property
    def cf_total(self) -> int:
        return len(self.cfs)

    @property
    def severity(self) -> float | None:
        if self.family_type not in (FamilyType.FRAGILE, FamilyType.STABLE_CORRECT):
            return None
        if not self.cfs:
            return None
        return self.cf_fail_count / self.cf_total
