"""Sample failed instances for manual failure-layer annotation.

Also provides inter-annotator agreement (IAA) helpers for the double-annotated
subset required by the annotation protocol: a raw agreement rate and Cohen's
kappa over two annotators' primary-failure-layer labels.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
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


@dataclass(frozen=True)
class AgreementResult:
    """Inter-annotator agreement over a double-annotated subset."""

    n: int
    agreement_rate: float
    cohen_kappa: float | None


def agreement_rate(labels_a: list[str], labels_b: list[str]) -> float:
    """Raw proportion of items on which the two annotators chose the same label."""
    if len(labels_a) != len(labels_b):
        raise ValueError("Label lists must have equal length")
    if not labels_a:
        return 0.0
    matches = sum(1 for a, b in zip(labels_a, labels_b, strict=True) if a == b)
    return matches / len(labels_a)


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """Cohen's kappa for two annotators over the same items.

    Returns None when kappa is undefined (no items, or perfect-chance-agreement
    where the expected agreement is 1.0, e.g. both annotators used a single label).
    """
    if len(labels_a) != len(labels_b):
        raise ValueError("Label lists must have equal length")
    n = len(labels_a)
    if n == 0:
        return None

    observed = agreement_rate(labels_a, labels_b)

    categories = set(labels_a) | set(labels_b)
    expected = 0.0
    for cat in categories:
        p_a = sum(1 for x in labels_a if x == cat) / n
        p_b = sum(1 for x in labels_b if x == cat) / n
        expected += p_a * p_b

    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def inter_annotator_agreement(annotations_a: dict[str, str], annotations_b: dict[str, str]) -> AgreementResult:
    """Compute IAA over instances annotated by both annotators.

    Args:
        annotations_a: instance_id -> primary failure layer (annotator A).
        annotations_b: instance_id -> primary failure layer (annotator B).

    Only instances present in both maps (and with non-empty labels in both) are
    used; the order is fixed by sorted instance_id for determinism.
    """
    shared = sorted(
        iid
        for iid in set(annotations_a) & set(annotations_b)
        if annotations_a[iid] and annotations_b[iid]
    )
    labels_a = [annotations_a[iid] for iid in shared]
    labels_b = [annotations_b[iid] for iid in shared]
    return AgreementResult(
        n=len(shared),
        agreement_rate=agreement_rate(labels_a, labels_b),
        cohen_kappa=cohen_kappa(labels_a, labels_b),
    )
