"""Bridge bcal's external-command protocol to bc_eval's M365 LLM API client."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, cast

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_CERT_FILE_ENV = "LLM_API_CERTIFICATE_FILE"
_RESPONSES_CONTEXT_FORMAT = "bcbench.responses.v1"
_MODEL_PROTOCOL_OVERRIDES = {"gpt-6-luna": "responses"}

# Separates the agent-under-test traffic from bc-eval's judge traffic (bc-eval's own agent host uses the same step).
_TAXONOMY_INFERENCE_STEP = "HostAgent"

_TOOLS_REASONING_EFFORT = "none"


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


def _protocol_for_model(model: str) -> str:
    return _MODEL_PROTOCOL_OVERRIDES.get(model, "chat-completions")


def _responses_input(messages: list[dict[str, object]], model: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    pending_calls: set[str] = set()
    for message in messages:
        role = message.get("role")
        if role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending_calls:
                raise ValueError("Tool result has no matching Responses function call.")
            pending_calls.remove(call_id)
            items.append({"type": "function_call_output", "call_id": call_id, "output": message.get("content", "")})
        elif role == "assistant":
            context = message.get("provider_context")
            if context is None:
                if message.get("tool_calls"):
                    raise ValueError("Responses tool-call history requires provider_context from a compatible BCal version.")
                items.append({"role": role, "content": message.get("content", "")})
                continue
            if not isinstance(context, dict) or context.get("format") != _RESPONSES_CONTEXT_FORMAT or context.get("model") != model:
                raise ValueError("Responses assistant history has incompatible provider_context.")
            output = _objects(context.get("output"), "Provider output")
            output_call_ids: set[str] = set()
            for item in output:
                if item.get("type") != "function_call":
                    continue
                call_id = item.get("call_id")
                if not isinstance(call_id, str):
                    raise TypeError("Responses function call IDs must be strings.")
                output_call_ids.add(call_id)
            calls = _objects(message.get("tool_calls") or [], "tool_calls")
            if output_call_ids != {call["id"] for call in calls} or pending_calls:
                raise ValueError("Responses provider_context does not match the assistant tool-call history.")
            pending_calls.update(output_call_ids)
            items.extend(output)
        elif role in ("system", "developer", "user"):
            items.append({"role": role, "content": message["content"]})
        else:
            raise ValueError(f"Unsupported BCal message role: {role!r}")
    if pending_calls:
        raise ValueError("Responses history is missing tool results.")
    return items


def _responses_kwargs(request: dict[str, object], model: str, messages: list[dict[str, object]]) -> dict[str, object]:
    effort = request.get("reasoning_effort") or "medium"
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
        "input": _responses_input(messages, model),
        "tools": tools,
        "reasoning": {"effort": effort, "context": "current_turn"},
        "max_output_tokens": request.get("max_completion_tokens", 16384),
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }


def _responses_completion(response: dict[str, object], model: str) -> dict[str, object]:
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
    message: dict[str, object] = {
        "role": "assistant",
        "content": "".join(text) or None,
        "provider_context": {"format": _RESPONSES_CONTEXT_FORMAT, "model": model, "output": response["output"]},
    }
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
    if _protocol_for_model(model) == "responses":
        response = _to_jsonable(client.responses.create(**_responses_kwargs(request, model, _objects(messages, "messages"))))
        json.dump(_responses_completion(response, model), sys.stdout)
        return 0

    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
        # bc-eval creates a new session per request; LLM API requires an empty ticket when none is cached.
        "extra_headers": {"x-sticky-route-session-ticket": ""},
    }
    tools = request.get("tools")
    if tools:
        kwargs["tools"] = tools
        # Chat Completions rejects function tools with reasoning enabled for these model families.
        kwargs["reasoning_effort"] = _TOOLS_REASONING_EFFORT
    else:
        reasoning_effort = request.get("reasoning_effort")
        if reasoning_effort is not None:
            kwargs["reasoning_effort"] = reasoning_effort

    response = client.chat.completions.create(**kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
