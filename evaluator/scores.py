from __future__ import annotations


class ResolutionRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        if metadata.get("infrastructure_failure", False):
            return None
        return metadata.get("resolved", False)


class BuildRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        if metadata.get("infrastructure_failure", False):
            return None
        return metadata.get("build", False)


class PrePatchFailedRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        if metadata.get("infrastructure_failure", False):
            return None
        return metadata.get("pre_patch_failed", False)


class PostPatchPassedRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        if metadata.get("infrastructure_failure", False):
            return None
        return metadata.get("post_patch_passed", False)


def _production_phase_score(metadata: dict, key: str) -> bool | None:
    status = metadata.get(key)
    if status == "passed":
        return True
    if status in {"failed", "invalid_submission"}:
        return False
    return None


class GeneratedTestValidity:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        return _production_phase_score(metadata, "generated_test_validity_status")


class GeneratedPairTransition:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        return _production_phase_score(metadata, "generated_pair_transition_status")


class FixBuild:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        return _production_phase_score(metadata, "fix_build_status")


class FixQuality:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        return _production_phase_score(metadata, "fix_quality_status")


class Resolution:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool | None:
        return _production_phase_score(metadata, "resolution_status")


class PrecisionScore:
    def __call__(self, *, metadata: dict, **kwargs: object) -> float:
        return float(metadata.get("precision", 0.0))


class RecallScore:
    def __call__(self, *, metadata: dict, **kwargs: object) -> float:
        return float(metadata.get("recall", 0.0))


class F1Score:
    def __call__(self, *, metadata: dict, **kwargs: object) -> float:
        return float(metadata.get("f1", 0.0))


class ValidReviewOutput:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool:
        return bool(metadata.get("valid_review_output", False))
