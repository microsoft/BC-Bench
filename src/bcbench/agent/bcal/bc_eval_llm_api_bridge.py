"""Bridge bcal's external-command protocol to bc_eval's M365 LLM API client."""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
import threading
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol, cast
from uuid import uuid4

if TYPE_CHECKING:
    from azure.core.credentials import TokenCredential

_CERT_FILE_ENV = "LLM_API_CERTIFICATE_FILE"
_TAXONOMY_INFERENCE_STEP = "HostAgent"
_DEFAULT_REASONING_EFFORT: str | None = None
_STICKY_ROUTE_TICKET_HEADER = "x-sticky-route-session-ticket"
_STICKY_ROUTE_BROKER_ADDRESS_ENV = "BCBENCH_STICKY_ROUTE_BROKER_ADDRESS"
_STICKY_ROUTE_BROKER_AUTH_ENV = "BCBENCH_STICKY_ROUTE_BROKER_AUTH"
_STICKY_ROUTE_BROKER_FAMILY_ENV = "BCBENCH_STICKY_ROUTE_BROKER_FAMILY"


class _RawResponse(Protocol):
    @property
    def headers(self) -> Mapping[str, str]:
        raise NotImplementedError

    def parse(self) -> object: ...


class _RawCompletions(Protocol):
    def create(self, **kwargs: object) -> object:
        raise NotImplementedError


class _TicketStore(Protocol):
    def get(self, model: str) -> str:
        pass

    def set(self, model: str, ticket: str) -> None:
        pass


class _MemoryTicketStore:
    def __init__(self) -> None:
        self._tickets: dict[str, str] = {}

    def get(self, model: str) -> str:
        return self._tickets.get(model, "")

    def set(self, model: str, ticket: str) -> None:
        self._tickets[model] = ticket


class _BrokerTicketStore:
    def __init__(self, address: str, family: str, authkey: bytes) -> None:
        self._address = address
        self._family = family
        self._authkey = authkey

    @classmethod
    def from_environment(cls) -> _BrokerTicketStore:
        address = os.environ.get(_STICKY_ROUTE_BROKER_ADDRESS_ENV)
        family = os.environ.get(_STICKY_ROUTE_BROKER_FAMILY_ENV)
        encoded_authkey = os.environ.get(_STICKY_ROUTE_BROKER_AUTH_ENV)
        if not address or family not in {"AF_PIPE", "AF_UNIX"} or not encoded_authkey:
            raise RuntimeError("The BCal LLM API bridge requires a session-scoped sticky-route broker.")
        try:
            authkey = urlsafe_b64decode(encoded_authkey.encode("ascii"))
        except ValueError as exc:
            raise RuntimeError("The session-scoped sticky-route broker authentication is invalid.") from exc
        return cls(address, family, authkey)

    def _request(self, request: dict[str, str]) -> str:
        try:
            connection = Client(self._address, family=self._family, authkey=self._authkey)
            with connection:
                connection.send(request)
                response = connection.recv()
        except (OSError, EOFError) as exc:
            raise RuntimeError("The session-scoped sticky-route broker is unavailable.") from exc
        if not isinstance(response, dict) or response.get("status") != "ok" or not isinstance(response.get("ticket"), str):
            raise RuntimeError("The session-scoped sticky-route broker returned an invalid response.")
        return cast(str, response["ticket"])

    def get(self, model: str) -> str:
        return self._request({"operation": "get", "model": model})

    def set(self, model: str, ticket: str) -> None:
        self._request({"operation": "set", "model": model, "ticket": ticket})


class StickyRouteTicketBroker:
    def __init__(self) -> None:
        self._authkey = secrets.token_bytes(32)
        self._tickets: dict[str, str] = {}
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        if os.name == "nt":
            self._family = "AF_PIPE"
            self._address = rf"\\.\pipe\bcbench-sticky-route-{uuid4().hex}"
        else:
            self._family = "AF_UNIX"
            self._temporary_directory = tempfile.TemporaryDirectory(prefix="bcbench-sticky-route-")
            self._address = str(Path(self._temporary_directory.name) / "broker.sock")
        self._listener = Listener(self._address, family=self._family, authkey=self._authkey)
        self._thread = threading.Thread(target=self._serve, name="bcbench-sticky-route-broker", daemon=True)
        self._thread.start()

    @property
    def environment(self) -> dict[str, str]:
        return {
            _STICKY_ROUTE_BROKER_ADDRESS_ENV: self._address,
            _STICKY_ROUTE_BROKER_FAMILY_ENV: self._family,
            _STICKY_ROUTE_BROKER_AUTH_ENV: urlsafe_b64encode(self._authkey).decode("ascii"),
        }

    def _serve(self) -> None:
        while True:
            try:
                connection = self._listener.accept()
            except OSError:
                return
            with connection:
                try:
                    request = connection.recv()
                except EOFError:
                    continue
                if not isinstance(request, dict):
                    connection.send({"status": "error", "ticket": ""})
                    continue
                operation = request.get("operation")
                model = request.get("model")
                if operation == "shutdown":
                    connection.send({"status": "ok", "ticket": ""})
                    return
                if not isinstance(model, str):
                    connection.send({"status": "error", "ticket": ""})
                    continue
                if operation == "get":
                    connection.send({"status": "ok", "ticket": self._tickets.get(model, "")})
                    continue
                ticket = request.get("ticket")
                if operation == "set" and isinstance(ticket, str):
                    self._tickets[model] = ticket
                    connection.send({"status": "ok", "ticket": ""})
                    continue
                connection.send({"status": "error", "ticket": ""})

    def close(self) -> None:
        try:
            connection = Client(self._address, family=self._family, authkey=self._authkey)
            with connection:
                connection.send({"operation": "shutdown"})
                connection.recv()
        except (OSError, EOFError):
            # Best-effort shutdown: the broker may already be gone or the control channel closed.
            # Continue with local cleanup and thread-termination checks below.
            pass
        self._listener.close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("The session-scoped sticky-route broker did not stop.")
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()


@contextmanager
def sticky_route_ticket_broker_environment() -> Iterator[dict[str, str]]:
    broker = StickyRouteTicketBroker()
    try:
        yield broker.environment
    finally:
        broker.close()


class _CompletionMethod:
    def __init__(self, create: Callable[..., object]) -> None:
        self._create = create

    def create(self, **kwargs: object) -> object:
        return self._create(**kwargs)


class StickyRouteSession:
    def __init__(self, ticket_store: _TicketStore | None = None) -> None:
        self._ticket_store = ticket_store or _MemoryTicketStore()

    def create(self, completions: _RawCompletions, kwargs: dict[str, object]) -> object:
        model = kwargs.get("model")
        if not isinstance(model, str):
            raise TypeError("Sticky-route requests require a string model.")

        request = dict(kwargs)
        ticket = self._ticket_store.get(model)
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
        self._ticket_store.set(model, response_ticket if isinstance(response_ticket, str) else "")
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

    create_compatible_client._bcbench_sticky_route_compat = True  # ty: ignore[unresolved-attribute]
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
    ticket_store = _BrokerTicketStore.from_environment()

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

    completion_method = _CompletionMethod(client.chat.completions.with_raw_response.create)
    response = StickyRouteSession(ticket_store).create(completion_method, kwargs)
    json.dump(_to_jsonable(response), sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
