from __future__ import annotations

from typing import Any


class ResolutionRate:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> bool:
        return bool(metadata.get("resolved", False))


class BuildRate:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> bool:
        return bool(metadata.get("build", False))


class PrePatchFailedRate:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> bool:
        return bool(metadata.get("pre_patch_failed", False))


class PostPatchPassedRate:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> bool:
        return bool(metadata.get("post_patch_passed", False))


class PrecisionScore:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> float:
        return float(metadata.get("precision", 0.0))


class RecallScore:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> float:
        return float(metadata.get("recall", 0.0))


class F1Score:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> float:
        return float(metadata.get("f1", 0.0))


class ValidReviewOutput:
    def __call__(self, *, metadata: dict[str, Any], **kwargs: object) -> bool:
        return bool(metadata.get("valid_review_output", False))
