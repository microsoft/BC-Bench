from __future__ import annotations

import sys
from pathlib import Path

# bc-eval loads this file via importlib.exec_module (not a package import) while resolving
# evaluators -- before running the nl2al lm_checklist judge -- so make the sibling taxonomy shim
# importable and install it here. This threads the M365 LLM API taxonomy/CoS headers onto the
# judge's CAPI calls (aka.ms/llmapi/waves-timeline); without them CAPI returns InvalidInferenceInput.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _capi_taxonomy import install as _install_capi_taxonomy

_install_capi_taxonomy()


class ResolutionRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool:
        return metadata.get("resolved", False)


class BuildRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool:
        return metadata.get("build", False)


class PrePatchFailedRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool:
        return metadata.get("pre_patch_failed", False)


class PostPatchPassedRate:
    def __call__(self, *, metadata: dict, **kwargs: object) -> bool:
        return metadata.get("post_patch_passed", False)


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
