from __future__ import annotations

import importlib
from collections.abc import Mapping
from copy import copy
from typing import Any

_LUNA_JUDGE_MODEL = "gpt-56-reasoning-nano-luna"
_LUNA_RESPONSE_FORMAT = {"type": "json_object"}
_TIMEOUT_REASON = "Agent timed out before producing output"


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


def _as_mapping(value: object) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            mapped = method()
            if isinstance(mapped, Mapping):
                return mapped
    return None


def _luna_output_text(response: object) -> tuple[Mapping[str, Any], str]:
    response_data = _as_mapping(response)
    if response_data is None:
        raise TypeError(f"Luna Responses API returned unsupported response type {type(response).__name__}")

    text_parts: list[str] = []
    output = response_data.get("output")
    if isinstance(output, list):
        for raw_item in output:
            item = _as_mapping(raw_item)
            if item is None:
                continue
            item_type = item.get("type")
            if item_type == "message" and item.get("role") == "assistant":
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for raw_part in content:
                    part = _as_mapping(raw_part)
                    if part is None or part.get("type") not in ("output_text", "text"):
                        continue
                    text = part.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
            elif item_type in ("output_text", "text"):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    text_parts.append(text)

    if not text_parts:
        raise ValueError("Luna Responses API response contained no assistant output_text content")
    return response_data, "".join(text_parts)


def _luna_chat_completion(response: object) -> dict[str, Any]:
    response_data, content = _luna_output_text(response)
    return {
        "id": response_data.get("id"),
        "object": "chat.completion",
        "created": response_data.get("created_at", response_data.get("created")),
        "model": response_data.get("model"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": response_data.get("stop_reason", "stop"),
            }
        ],
    }


def _luna_responses_params(request: dict[str, object]) -> dict[str, object]:
    supported = {
        "max_tokens",
        "messages",
        "model",
        "reasoning_effort",
        "response_format",
        "span_info",
    }
    unsupported = sorted(set(request) - supported)
    if unsupported:
        raise ValueError(f"Unsupported Luna LM Checklist request arguments: {', '.join(unsupported)}")
    if request.get("model") != _LUNA_JUDGE_MODEL:
        raise ValueError("Luna Responses adapter received a non-Luna model")

    params = {
        "model": request["model"],
        "input": request["messages"],
    }
    if (max_tokens := request.get("max_tokens")) is not None:
        params["max_output_tokens"] = max_tokens
    if (response_format := request.get("response_format")) is not None:
        if response_format != _LUNA_RESPONSE_FORMAT:
            raise ValueError(f"Unsupported Luna LM Checklist response format: {response_format!r}")
        params["text"] = {"format": dict(_LUNA_RESPONSE_FORMAT)}
    if (reasoning_effort := request.get("reasoning_effort")) is not None:
        params["reasoning"] = {"effort": reasoning_effort}
    return params


def _luna_responses_client(client: object) -> object:
    oai = importlib.import_module("autoevals.oai")
    resolved_client = oai.prepare_openai(client=client, is_async=False)
    adapted_client = copy(resolved_client)

    def complete(**request: object) -> dict[str, Any]:
        response = resolved_client.openai.responses.create(**_luna_responses_params(request))
        return _luna_chat_completion(response)

    adapted_client.complete = complete
    return adapted_client


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


class LmChecklist:
    def __new__(cls) -> object:
        # bc-eval loads a custom class with this name before its built-in scorer.
        module = importlib.import_module("bc_eval.scorers.autoeval.lmchecklist")
        scorer = module.LmChecklist()
        request_args = scorer._request_args
        run_eval_sync = scorer._run_eval_sync

        def responses_compatible_request_args(output: object, expected: object = None, **kwargs: object) -> dict[str, Any]:
            request = request_args(output, expected, **kwargs)
            model = str(request.get("model", ""))
            # Autoevals routes GPT-5 models through Responses, where assistant content is output.
            if model.startswith("gpt-5"):
                request["messages"] = _responses_compatible_messages(request["messages"])
            if model == _LUNA_JUDGE_MODEL:
                request.pop("temperature", None)
                request["client"] = _luna_responses_client(request.get("client"))
            return request

        def timeout_aware_run_eval_sync(output: object, expected: object = None, **kwargs: object) -> object:
            metadata = kwargs.get("metadata")
            if isinstance(metadata, dict) and metadata.get("timeout") is True:
                return _timeout_scores(scorer, expected, metadata)
            return run_eval_sync(output, expected, **kwargs)

        scorer._request_args = responses_compatible_request_args
        scorer._run_eval_sync = timeout_aware_run_eval_sync
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
