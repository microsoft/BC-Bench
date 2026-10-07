from __future__ import annotations

import importlib
from typing import Any

_LUNA_JUDGE_MODEL = "gpt-56-reasoning-nano-luna"


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
            model = str(request.get("model", ""))
            # Autoevals routes GPT-5 models through Responses, where assistant content is output.
            if model.startswith("gpt-5"):
                request["messages"] = _responses_compatible_messages(request["messages"])
            if model == _LUNA_JUDGE_MODEL:
                request.pop("temperature", None)
            return request

        scorer._request_args = responses_compatible_request_args
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
