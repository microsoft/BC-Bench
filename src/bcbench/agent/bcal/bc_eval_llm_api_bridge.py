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

# Separates the agent-under-test traffic from bc-eval's judge traffic (bc-eval's own agent host uses the same step).
_TAXONOMY_INFERENCE_STEP = "HostAgent"

# Reasoning effort (not all models support this parameter), different models might have different available values:
# Set to None to omit the parameter entirely (lets the model/service use its own default).
_DEFAULT_REASONING_EFFORT: str | None = None
_RESPONSES_CONTEXT = "bcbench.responses.v1"


def _to_jsonable(value: object) -> dict[str, object]:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json", exclude_none=True, by_alias=True)
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


def _object(value: object, description: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{description} must be a JSON object.")
    return cast(dict[str, object], value)


def _objects(value: object, description: str) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise TypeError(f"{description} must be an array.")
    return [_object(item, description) for item in value]


def _responses_input(messages: list[dict[str, object]], model: str) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    pending_calls: set[str] = set()
    for message in messages:
        role = message.get("role")
        if role == "assistant":
            context = message.get("provider_context")
            if not isinstance(context, dict) or context.get("format") != _RESPONSES_CONTEXT or context.get("model") != model:
                raise ValueError("Responses assistant history requires matching provider_context. Use a BCal build with opaque provider-context support.")
            output = _objects(context.get("output"), "Provider output")
            calls = _objects(message.get("tool_calls", []), "Assistant tool calls")
            output_ids = {item["call_id"] for item in output if item.get("type") == "function_call"}
            if output_ids != {call["id"] for call in calls} or pending_calls:
                raise ValueError("Responses provider context does not match the assistant tool-call history.")
            for call_id in output_ids:
                if not isinstance(call_id, str):
                    raise TypeError("Responses function call IDs must be strings.")
                pending_calls.add(call_id)
            items.extend(output)
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if not isinstance(call_id, str) or call_id not in pending_calls:
                raise ValueError("Tool result has no matching Responses function call.")
            pending_calls.remove(call_id)
            items.append({"type": "function_call_output", "call_id": call_id, "output": message.get("content", "")})
        elif role in ("system", "developer", "user"):
            items.append({"role": role, "content": message.get("content", "")})
        else:
            raise ValueError(f"Unsupported message role: {role!r}")
    if pending_calls:
        raise ValueError("Responses history is missing tool results.")
    return items


def _responses_tools(tools: object) -> list[dict[str, object]]:
    converted: list[dict[str, object]] = []
    for tool in _objects(tools, "Tools"):
        if tool.get("type") != "function":
            raise ValueError("The BCal Responses bridge only supports function tools.")
        function = _object(tool.get("function"), "Function tool")
        # Responses defaults to strict schemas; Chat Completions does not.
        converted.append({"type": "function", **function, "strict": function.get("strict", False)})
    return converted


def _responses_completion(response: dict[str, object], model: str) -> dict[str, object]:
    if response.get("status") != "completed":
        raise RuntimeError(f"Responses request did not complete: {response.get('status')}; {response.get('error') or response.get('incomplete_details')}")
    output = _objects(response.get("output"), "Response output")
    text: list[str] = []
    calls: list[dict[str, object]] = []
    for item in output:
        kind = item.get("type")
        if kind == "reasoning":
            if not item.get("encrypted_content"):
                raise RuntimeError("Responses returned reasoning without encrypted continuation content.")
        elif kind == "function_call":
            calls.append({"id": item["call_id"], "type": "function", "function": {"name": item["name"], "arguments": item["arguments"]}})
        elif kind == "message":
            for content in _objects(item.get("content"), "Response message content"):
                content_type = content.get("type")
                if content_type not in ("output_text", "refusal"):
                    raise ValueError(f"Unsupported Responses content type: {content_type!r}")
                value = content.get("text" if content_type == "output_text" else "refusal")
                if not isinstance(value, str):
                    raise TypeError("Response message text must be a string.")
                text.append(value)
        else:
            raise ValueError(f"Unsupported Responses output type: {kind!r}")
    usage = _object(response.get("usage"), "Response usage")
    message: dict[str, object] = {
        "role": "assistant",
        "content": "\n".join(text) or None,
        "provider_context": {"format": _RESPONSES_CONTEXT, "model": model, "output": output},
    }
    if calls:
        message["tool_calls"] = calls
    return {
        "id": response.get("id"),
        "model": response.get("model"),
        "choices": [{"index": 0, "finish_reason": "tool_calls" if calls else "stop", "message": message}],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "prompt_tokens_details": usage.get("input_tokens_details", {}),
            "completion_tokens_details": usage.get("output_tokens_details", {}),
        },
    }


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
    headers = {"x-sticky-route-session-ticket": "opt-out"}
    reasoning_effort = request.get("reasoning_effort", _DEFAULT_REASONING_EFFORT)
    if model == "gpt-56-reasoning-sol":
        kwargs: dict[str, object] = {
            "model": model,
            "input": _responses_input(_objects(messages, "Messages"), model),
            "max_output_tokens": request.get("max_completion_tokens", 16384),
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "extra_headers": headers,
        }
        if request.get("tools"):
            kwargs["tools"] = _responses_tools(request["tools"])
        if reasoning_effort is not None:
            kwargs["reasoning"] = {"effort": reasoning_effort}
        response = client.responses.create(**kwargs)
        json.dump(_responses_completion(_to_jsonable(response), model), sys.stdout)
        return 0

    kwargs = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
        # The bridge is a fresh process per turn and cannot retain opaque routing tickets.
        "extra_headers": headers,
    }
    if request.get("tools"):
        kwargs["tools"] = request["tools"]

    if reasoning_effort is not None:
        kwargs["reasoning_effort"] = reasoning_effort

    response = client.chat.completions.create(**kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
