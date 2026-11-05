"""Bridge bcal's external-command protocol to bc_eval's M365 LLM API client."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol, cast

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_CERT_FILE_ENV = "LLM_API_CERTIFICATE_FILE"
_TAXONOMY_INFERENCE_STEP = "HostAgent"
_DEFAULT_REASONING_EFFORT: str | None = None
_STICKY_ROUTE_TICKET_HEADER = "x-sticky-route-session-ticket"


class _RawResponse(Protocol):
    @property
    def headers(self) -> Mapping[str, str]: ...

    def parse(self) -> object: ...


class _RawCompletions(Protocol):
    def create(self, **kwargs: object) -> object: ...


class _CompletionMethod:
    def __init__(self, create: Callable[..., object]) -> None:
        self._create = create

    def create(self, **kwargs: object) -> object:
        return self._create(**kwargs)


class StickyRouteSession:
    def __init__(self) -> None:
        self._tickets: dict[str, str] = {}

    def create(self, completions: _RawCompletions, kwargs: dict[str, object]) -> object:
        model = kwargs.get("model")
        if not isinstance(model, str):
            raise TypeError("Sticky-route requests require a string model.")

        request = dict(kwargs)
        ticket = self._tickets.get(model, "")
        request["extra_headers"] = {
            **cast(dict[str, str], request.get("extra_headers", {})),
            _STICKY_ROUTE_TICKET_HEADER: ticket,
        }
        try:
            response = cast(_RawResponse, completions.create(**request))
        except Exception:
            if ticket:
                raise RuntimeError("LLM API rejected its response-derived sticky-route session ticket.") from None
            raise

        response_ticket = response.headers.get(_STICKY_ROUTE_TICKET_HEADER, "")
        self._tickets[model] = response_ticket if isinstance(response_ticket, str) else ""
        return response.parse()


def install_sticky_route_compat() -> None:
    from bc_eval.llm import llm_api

    if getattr(llm_api.create_llm_api_client, "_bcbench_sticky_route_compat", False):
        return

    create_llm_api_client = llm_api.create_llm_api_client

    def create_compatible_client(*args: object, **kwargs: object) -> object:
        client = create_llm_api_client(*args, **kwargs)
        completions = client.chat.completions
        completion_method = _CompletionMethod(completions.with_raw_response.create)
        sticky_route_session = StickyRouteSession()

        def create(**request: object) -> object:
            return sticky_route_session.create(completion_method, request)

        completions.create = create
        return client

    create_compatible_client._bcbench_sticky_route_compat = True  # type: ignore[attr-defined]
    llm_api.create_llm_api_client = create_compatible_client


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
    cert_path = os.environ.get(_CERT_FILE_ENV)
    if not cert_path:
        return None

    cert_file = Path(cert_path)
    if not cert_file.is_file():
        raise RuntimeError(f"{_CERT_FILE_ENV}={cert_path} is set but the file does not exist.")

    from azure.identity import CertificateCredential

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
        install_sticky_route_compat()
        from bc_eval.llm.llm_api import LlmApiSettings, create_llm_api_client
    except ImportError as exc:
        raise RuntimeError("bc-eval>=0.6.0 is required for the bcal LLM API bridge.") from exc

    settings = LlmApiSettings.from_env()
    client = create_llm_api_client(
        inference_step=_TAXONOMY_INFERENCE_STEP,
        settings=settings,
        credential=_local_certificate_credential(settings.tenant_id, settings.client_id),
    )
    kwargs: dict[str, object] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": request.get("max_completion_tokens", 16384),
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
