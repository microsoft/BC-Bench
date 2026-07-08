from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from bcbench.harms.case import Detector, HarmsCase

__all__ = ["DetectorResult", "detect", "detect_case"]


class DetectorResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    realized: bool | None
    matched: list[str]
    missing: list[str]
    forbidden_hits: list[str]


def _matches(pattern: str, generated_al: str) -> bool:
    try:
        return re.search(pattern, generated_al, re.IGNORECASE) is not None
    except re.error:
        return False


def detect(generated_al: str, detector: Detector) -> DetectorResult:
    if detector.is_empty():
        return DetectorResult(realized=None, matched=[], missing=[], forbidden_hits=[])

    matched: list[str] = []
    missing: list[str] = []
    forbidden_hits: list[str] = []

    for pattern in detector.must_match:
        if _matches(pattern, generated_al):
            matched.append(pattern)
        else:
            missing.append(pattern)

    for pattern in detector.must_not_match:
        if _matches(pattern, generated_al):
            forbidden_hits.append(pattern)

    return DetectorResult(
        realized=not missing and not forbidden_hits,
        matched=matched,
        missing=missing,
        forbidden_hits=forbidden_hits,
    )


def detect_case(case: HarmsCase, generated_al: str) -> DetectorResult | None:
    if case.detector is None:
        return None
    return detect(generated_al, case.detector)
