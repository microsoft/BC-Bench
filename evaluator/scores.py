from __future__ import annotations

import importlib
from typing import Any

_TIMEOUT_REASON = "Agent timed out before producing output"


def _timeout_scores(scorer: object, expected: object, metadata: dict[str, Any]) -> list[object]:
    if not isinstance(expected, dict):
        raise TypeError("expected must be a dict containing an 'assertions' key")
    assertions = expected.get("assertions")
    if not isinstance(assertions, list):
        raise TypeError("expected['assertions'] must be a list")

    judged = []
    for index, assertion in enumerate(assertions):
        if not isinstance(assertion, dict):
            raise TypeError(f"expected['assertions'][{index}] must be a dict")
        if "text" not in assertion:
            raise ValueError(f"expected['assertions'][{index}] must contain a 'text' key")
        judged.append({**assertion, "pass": False, "reasoning": _TIMEOUT_REASON})

    score_metadata = {"assertions": judged, "error": _TIMEOUT_REASON}
    metadata["assertionResults"] = judged
    score = importlib.import_module("autoevals").Score
    rate = getattr(scorer, "_rate", None)
    if not callable(rate):
        raise TypeError("LM Checklist scorer does not provide a callable '_rate'")
    return [
        score(name="pass_rate", score=rate(judged), metadata=score_metadata),
        score(name="critical_pass_rate", score=rate(judged, "critical"), metadata=score_metadata),
        score(name="expected_pass_rate", score=rate(judged, "expected"), metadata=score_metadata),
        score(name="aspirational_pass_rate", score=rate(judged, "aspirational"), metadata=score_metadata),
        score(name="test_passed", score=0.0, metadata=score_metadata),
    ]


def _infrastructure_error_scores(metadata: dict[str, Any]) -> list[object]:
    error = str(metadata.get("Error") or metadata.get("error_message") or "Infrastructure error")
    score_metadata = {"error": error}
    score = importlib.import_module("autoevals").Score
    return [
        score(name="pass_rate", score=None, metadata=score_metadata),
        score(name="critical_pass_rate", score=None, metadata=score_metadata),
        score(name="expected_pass_rate", score=None, metadata=score_metadata),
        score(name="aspirational_pass_rate", score=None, metadata=score_metadata),
        score(name="test_passed", score=None, metadata=score_metadata),
    ]


class LmChecklist:
    def __new__(cls) -> object:
        module = importlib.import_module("bc_eval.scorers.autoeval.lmchecklist")
        scorer = module.LmChecklist()
        run_eval_sync = scorer._run_eval_sync

        def failure_aware_run_eval_sync(output: object, expected: object = None, **kwargs: object) -> object:
            metadata = kwargs.get("metadata")
            if isinstance(metadata, dict):
                metadata["core_score_name"] = "test_passed"
                if metadata.get("infrastructure_error") is True:
                    return _infrastructure_error_scores(metadata)
                if metadata.get("timeout") is True:
                    return _timeout_scores(scorer, expected, metadata)
            return run_eval_sync(output, expected, **kwargs)

        scorer._run_eval_sync = failure_aware_run_eval_sync
        return scorer


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
