"""Bridge bcal's external-command protocol to bc_eval's CAPI OpenAI-compatible client."""

from __future__ import annotations

import json
import sys
import time
from typing import BinaryIO, cast

_TRANSIENT_RETRY_ATTEMPTS = 3
_TRANSIENT_RETRY_BACKOFF_SEC = 2.0


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

    raise TypeError(f"Unsupported response type from bc_eval CAPI bridge: {type(value)!r}")


def _load_request(input_stream: BinaryIO) -> dict[str, object]:
    request_raw = json.loads(input_stream.read().decode("utf-8-sig"))
    if not isinstance(request_raw, dict):
        raise TypeError("External AI request must be a JSON object.")

    return cast(dict[str, object], request_raw)


def _create_with_retry(client: object, kwargs: dict[str, object]) -> object:
    # Retry transient CAPI failures (e.g. upstream OpenAI returns 5xx wrapped as DependencyFailure / server_error).
    from azure.core.exceptions import HttpResponseError

    last_exc: HttpResponseError | None = None
    for attempt in range(_TRANSIENT_RETRY_ATTEMPTS):
        try:
            return client.chat.completions.create(**kwargs)  # type: ignore[attr-defined]
        except HttpResponseError as exc:
            last_exc = exc
            if attempt == _TRANSIENT_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(_TRANSIENT_RETRY_BACKOFF_SEC * (2**attempt))
    assert last_exc is not None
    raise last_exc


def main() -> int:
    request = _load_request(sys.stdin.buffer)
    model = request.get("model")
    messages = request.get("messages")
    if not isinstance(model, str):
        raise TypeError("External AI request requires a string model.")

    if not isinstance(messages, list):
        raise TypeError("External AI request requires a messages array.")

    try:
        from bc_eval.capi.capi_model import CapiModel
    except ImportError as exc:
        raise RuntimeError("bc-eval[capi] is required for the bcal CAPI bridge.") from exc

    client = CapiModel()
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
    }
    if request.get("tools"):
        kwargs["tools"] = request["tools"]

    response = _create_with_retry(client, kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
