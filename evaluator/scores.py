from __future__ import annotations

import importlib
from typing import Any


def _responses_compatible_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            **message,
            "content": [{"type": "output_text", "text": content}],
        }
        if message.get("role") == "assistant" and isinstance((content := message.get("content")), str)
        else message
        for message in messages
    ]


class LmChecklist:
    def __new__(cls) -> object:
        # bc-eval loads a custom class with this name before its built-in scorer.
        module = importlib.import_module("bc_eval.scorers.autoeval.lmchecklist")
        scorer = module.LmChecklist()
        request_args = scorer._request_args

        def responses_compatible_request_args(output: object, expected: object = None, **kwargs: object) -> dict[str, Any]:
            request = request_args(output, expected, **kwargs)
            # Autoevals routes GPT-5 models through Responses, where assistant content is output.
            if str(request.get("model", "")).startswith("gpt-5"):
                request["messages"] = _responses_compatible_messages(request["messages"])
            return request

        scorer._request_args = responses_compatible_request_args
        return scorer


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
