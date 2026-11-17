"""Bridge bcal's external-command protocol to bc_eval's M365 LLM API client."""

from __future__ import annotations

import json
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_CERT_FILE_ENV = "LLM_API_CERTIFICATE_FILE"
_STATE_DIR_ENV = "BCAL_LLM_STATE_DIR"

# Separates the agent-under-test traffic from bc-eval's judge traffic (bc-eval's own agent host uses the same step).
_TAXONOMY_INFERENCE_STEP = "HostAgent"

# Reasoning effort (not all models support this parameter), different models might have different available values:
# Set to None to omit the parameter entirely (lets the model/service use its own default).
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

    raise TypeError(f"Unsupported response type from bc_eval LLM API bridge: {type(value)!r}")


def _load_request(input_stream: BinaryIO) -> dict[str, object]:
    request_raw = json.loads(input_stream.read().decode("utf-8-sig"))
    if not isinstance(request_raw, dict):
        raise TypeError("External AI request must be a JSON object.")

    return cast(dict[str, object], request_raw)


def _local_certificate_credential(tenant_id: str, client_id: str) -> TokenCredential | None:
    """Credential from a locally staged PFX, or None to let bc-eval sign through Key Vault.

    The bridge is spawned once per agent turn, so bc-eval's default credential would hit Key Vault
    and AAD on every turn; with N parallel jobs * M turns this rate-limits Key Vault.
    """
    cert_path = os.environ.get(_CERT_FILE_ENV)
    if not cert_path:
        return None

    cert_file = Path(cert_path)
    if not cert_file.is_file():
        raise RuntimeError(f"{_CERT_FILE_ENV}={cert_path} is set but the file does not exist.")

    from azure.identity import CertificateCredential

    # send_certificate_chain=True sends the x5c header (SNI auth), which the app registration
    # validates against; without it AAD returns AADSTS700027.
    return CertificateCredential(
        tenant_id=tenant_id,
        client_id=client_id,
        certificate_path=str(cert_file),
        send_certificate_chain=True,
    )


def _objects(value: object, name: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"{name} must be an array of objects.")
    return cast(list[dict[str, object]], value)


def _tool_state_path(state_dir: Path, model: str, calls: list[dict[str, object]]) -> Path:
    call_id = calls[0]["id"]
    if not isinstance(call_id, str) or not call_id:
        raise ValueError("A tool call requires a non-empty string id.")
    return state_dir / f"{sha256(f'{model}:{call_id}'.encode()).hexdigest()}.json"


def _responses_input(messages: list[dict[str, object]], model: str, state_dir: Path) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": message["content"]})
        elif role == "assistant" and message.get("tool_calls"):
            calls = _objects(message["tool_calls"], "tool_calls")
            # BCal reconstructs assistant messages and drops opaque reasoning. Restore the exact
            # Responses output, including encrypted reasoning and function-call item IDs.
            path = _tool_state_path(state_dir, model, calls)
            items.extend(_objects(json.loads(path.read_text(encoding="utf-8")), "Saved Responses output"))
        elif role in ("system", "developer", "user", "assistant"):
            items.append({"role": role, "content": message["content"]})
        else:
            raise ValueError(f"Unsupported BCal message role: {role!r}")
    return items


def _responses_kwargs(request: dict[str, object], model: str, messages: list[dict[str, object]], state_dir: Path) -> dict[str, object]:
    effort = request.get("reasoning_effort") or "medium"
    if effort in ("none", "minimal"):
        raise ValueError("GPT-6 Luna evaluations require reasoning_effort of low or higher.")
    tools = []
    for tool in _objects(request.get("tools") or [], "tools"):
        if tool.get("type") != "function":
            raise ValueError("Only function tools are supported by the BCal Responses bridge.")
        function = tool["function"]
        if not isinstance(function, dict):
            raise TypeError("A function tool requires a function object.")
        # Responses otherwise enables strict schemas, unlike Chat Completions.
        tools.append({**function, "type": "function", "strict": False})
    return {
        "model": model,
        "input": _responses_input(messages, model, state_dir),
        "tools": tools,
        "reasoning": {"effort": effort, "context": "current_turn"},
        "max_output_tokens": request.get("max_completion_tokens", 16384),
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }


def _responses_completion(response: dict[str, object]) -> dict[str, object]:
    if response.get("status") != "completed":
        raise RuntimeError(f"LLM API Responses request did not complete: {response.get('status')}; {response.get('error') or response.get('incomplete_details')}")
    text: list[str] = []
    calls: list[dict[str, object]] = []
    for item in _objects(response.get("output"), "Responses output"):
        match item.get("type"):
            case "reasoning":
                if not item.get("encrypted_content"):
                    raise RuntimeError("LLM API did not return encrypted reasoning for stateless replay.")
            case "message":
                for content in _objects(item.get("content"), "Response message content"):
                    match content.get("type"):
                        case "output_text":
                            text.append(str(content["text"]))
                        case "refusal":
                            text.append(str(content["refusal"]))
                        case _:
                            raise ValueError(f"Unsupported Responses content type: {content.get('type')!r}")
            case "function_call":
                calls.append({"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item["arguments"]}})
            case _:
                raise ValueError(f"Unsupported Responses output type: {item.get('type')!r}")
    if not text and not calls:
        raise RuntimeError("LLM API returned neither text nor tool calls.")
    message: dict[str, object] = {"role": "assistant", "content": "".join(text) or None}
    if calls:
        message["tool_calls"] = calls
    result: dict[str, object] = {
        "id": response["id"],
        "object": "chat.completion",
        "created": response["created_at"],
        "model": response["model"],
        "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": message}],
    }
    usage = response.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {
            "prompt_tokens": usage["input_tokens"],
            "completion_tokens": usage["output_tokens"],
            "total_tokens": usage["total_tokens"],
            "prompt_tokens_details": usage.get("input_tokens_details"),
            "completion_tokens_details": usage.get("output_tokens_details"),
        }
    return result


def main() -> int:
    request = _load_request(sys.stdin.buffer)
    model = request.get("model")
    messages = request.get("messages")
    if not isinstance(model, str):
        raise TypeError("External AI request requires a string model.")

    if not isinstance(messages, list):
        raise TypeError("External AI request requires a messages array.")

    try:
        from bc_eval.llm.llm_api import LlmApiSettings, create_llm_api_client
    except ImportError as exc:
        raise RuntimeError("bc-eval>=0.6.0 is required for the bcal LLM API bridge.") from exc

    settings = LlmApiSettings.from_env()
    client = create_llm_api_client(
        inference_step=_TAXONOMY_INFERENCE_STEP,
        settings=settings,
        credential=_local_certificate_credential(settings.tenant_id, settings.client_id),
    )
    if model == "gpt-6-luna":
        state_dir_value = os.environ.get(_STATE_DIR_ENV)
        if not state_dir_value:
            raise RuntimeError(f"{_STATE_DIR_ENV} is required for GPT-6 Luna reasoning continuity. Run through bcbench or set a per-run temporary directory.")
        state_dir = Path(state_dir_value)
        state_dir.mkdir(parents=True, exist_ok=True)
        response = _to_jsonable(client.responses.create(**_responses_kwargs(request, model, _objects(messages, "messages"), state_dir)))
        completion = _responses_completion(response)
        message = _objects(completion["choices"], "choices")[0]["message"]
        if isinstance(message, dict) and message.get("tool_calls"):
            path = _tool_state_path(state_dir, model, _objects(message["tool_calls"], "tool_calls"))
            path.write_text(json.dumps(response["output"]), encoding="utf-8")
        json.dump(completion, sys.stdout)
        return 0

    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
        # bc-eval creates a new session per request; LLM API requires an empty ticket when none is cached.
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }
    if request.get("tools"):
        kwargs["tools"] = request["tools"]

    reasoning_effort = request.get("reasoning_effort", _DEFAULT_REASONING_EFFORT)
    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    response = client.chat.completions.create(**kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
