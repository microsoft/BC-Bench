"""Bridge BCal's external-command protocol to bc-eval's direct M365 LLM API client."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import BinaryIO, cast

_INFRASTRUCTURE_ERROR_FILE_ENV = "BCBENCH_LLM_API_ERROR_FILE"
_PROVIDER = "llm_api"
_TAXONOMY_AGENT = "BC-Bench"
_TAXONOMY_INFERENCE_STEP = "BCal"

# Not every model supports reasoning_effort. None lets the service select its default.
_DEFAULT_REASONING_EFFORT: str | None = None


def _to_jsonable(value: object) -> dict[str, object]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json", exclude_none=True)
        if isinstance(dumped, dict):
            return cast(dict[str, object], dumped)

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        dumped = to_dict()
        if isinstance(dumped, dict):
            return cast(dict[str, object], dumped)

    if isinstance(value, dict):
        return cast(dict[str, object], value)

    raise TypeError(f"Unsupported response type from bc-eval LLM API bridge: {type(value)!r}")


def _load_request(input_stream: BinaryIO) -> dict[str, object]:
    request_raw = json.loads(input_stream.read().decode("utf-8-sig"))
    if not isinstance(request_raw, dict):
        raise TypeError("External AI request must be a JSON object.")

    return cast(dict[str, object], request_raw)


def _infrastructure_error_file() -> Path | None:
    path = os.environ.get(_INFRASTRUCTURE_ERROR_FILE_ENV)
    return Path(path) if path else None


def _clear_infrastructure_error() -> None:
    error_file = _infrastructure_error_file()
    if error_file is not None:
        error_file.unlink(missing_ok=True)


def _http_status_code(error: Exception) -> int | None:
    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    return status_code if isinstance(status_code, int) else None


def _record_infrastructure_error(error: Exception) -> None:
    status_code = _http_status_code(error)
    error_file = _infrastructure_error_file()
    if error_file is None or status_code is None or not 500 <= status_code <= 599:
        return

    error_file.parent.mkdir(parents=True, exist_ok=True)
    error_file.write_text(
        json.dumps(
            {
                "provider": _PROVIDER,
                "status_code": status_code,
                "message": str(error),
            }
        ),
        encoding="utf-8",
    )


def _create_completion(client: object, kwargs: dict[str, object]) -> object:
    _clear_infrastructure_error()
    try:
        return client.chat.completions.create(**kwargs)  # ty: ignore[unresolved-attribute]
    except Exception as error:
        _record_infrastructure_error(error)
        raise


def _is_reasoning_model(model: str) -> bool:
    return model.startswith("gpt-5") and "-chat" not in model


def _completion_kwargs(request: dict[str, object], model: str, messages: list[object]) -> dict[str, object]:
    max_completion_tokens = request.get("max_completion_tokens")
    if max_completion_tokens is None:
        max_completion_tokens = request.get("max_tokens")
    if max_completion_tokens is None:
        max_completion_tokens = 16384

    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    if request.get("tools"):
        kwargs["tools"] = request["tools"]
    if request.get("tool_choice") is not None:
        kwargs["tool_choice"] = request["tool_choice"]

    temperature = request.get("temperature")
    if temperature is not None and not _is_reasoning_model(model):
        kwargs["temperature"] = temperature

    reasoning_effort = request.get("reasoning_effort", _DEFAULT_REASONING_EFFORT)
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    return kwargs


def main() -> int:
    request = _load_request(sys.stdin.buffer)
    model = request.get("model")
    messages = request.get("messages")
    if not isinstance(model, str):
        raise TypeError("External AI request requires a string model.")

    if not isinstance(messages, list):
        raise TypeError("External AI request requires a messages array.")

    try:
        from bc_eval.llm.providers import create_openai_compatible_client
    except ImportError as exc:
        raise RuntimeError("bc-eval==0.6.0 is required for the BCal LLM API bridge.") from exc

    client = create_openai_compatible_client(
        provider=_PROVIDER,
        taxonomy_agent=_TAXONOMY_AGENT,
        taxonomy_inference_step=_TAXONOMY_INFERENCE_STEP,
    )
    kwargs = _completion_kwargs(request, model, messages)
    response = _create_completion(client, kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
