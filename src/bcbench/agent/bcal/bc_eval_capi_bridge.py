"""Bridge bcal's external-command protocol to bc_eval's CAPI OpenAI-compatible client."""

from __future__ import annotations

import json
import sys
from typing import cast


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


def main() -> int:
    request_raw = json.load(sys.stdin)
    if not isinstance(request_raw, dict):
        raise TypeError("External AI request must be a JSON object.")

    request = cast(dict[str, object], request_raw)
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

    response = client.chat.completions.create(**kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
