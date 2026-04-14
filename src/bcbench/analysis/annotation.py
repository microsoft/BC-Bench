"""Sample failed instances for manual failure-layer annotation."""

from __future__ import annotations

import csv
from pathlib import Path

from bcbench.analysis.family import FamilyOutcome, FamilyType, InstanceResult
from bcbench.logger import get_logger

logger = get_logger(__name__)

ANNOTATION_COLUMNS = [
    "family_id",
    "instance_id",
    "family_type",
    "pattern",
    "failure_layer",
    "base_passed",
    "cf_passed",
    "primary_failure_layer",
    "error_evidence",
    "annotator_notes",
]


def sample_failures(
    families: list[FamilyOutcome],
    max_samples: int | None = None,
) -> list[dict[str, str]]:
    priority = [FamilyType.FRAGILE, FamilyType.UNSOLVED, FamilyType.INCONSISTENT]
    sorted_families = sorted(families, key=lambda f: priority.index(f.family_type) if f.family_type in priority else 99)

    rows: list[dict[str, str]] = []
    for family in sorted_families:
        if family.family_type == FamilyType.STABLE_CORRECT:
            continue

        if not family.base.passed:
            rows.append(_make_row(family, family.base))

        for cf in family.cfs:
            if not cf.passed:
                rows.append(_make_row(family, cf))

        if max_samples and len(rows) >= max_samples:
            rows = rows[:max_samples]
            break

    return rows


def _make_row(family: FamilyOutcome, instance: InstanceResult) -> dict[str, str]:
    return {
        "family_id": family.family_id,
        "instance_id": instance.instance_id,
        "family_type": family.family_type.value,
        "pattern": str(family.pattern),
        "failure_layer": family.failure_layer.value if family.failure_layer else "",
        "base_passed": str(int(family.base.passed)),
        "cf_passed": ",".join(str(int(cf.passed)) for cf in family.cfs),
        "primary_failure_layer": "",
        "error_evidence": "",
        "annotator_notes": "",
    }


def write_annotation_csv(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ANNOTATION_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Wrote {len(rows)} annotation rows to {output_path}")
