from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from bcbench.agent.bcal.bc_eval_llm_api_bridge import (
    _STICKY_ROUTE_TICKET_HEADER,
    StickyRouteSession,
    install_sticky_route_compat,
)


@dataclass
class _Response:
    headers: dict[str, str]


class _ServiceError(Exception):
    def __init__(self, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.response = _Response(headers or {})


class _Completions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _ticket_required(ticket: str | None = None) -> _ServiceError:
    headers = {_STICKY_ROUTE_TICKET_HEADER: ticket} if ticket is not None else {}
    return _ServiceError(
        f"LLM API: Required taxonomy data {_STICKY_ROUTE_TICKET_HEADER} not provided.",
        headers,
    )


def test_install_compat_wraps_initial_and_subsequent_requests(monkeypatch: pytest.MonkeyPatch):
    completions = _Completions([_ticket_required("secret-ticket"), {"id": "first"}, {"id": "second"}])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    def create_client(*args: object, **kwargs: object) -> Any:
        return client

    bc_eval = ModuleType("bc_eval")
    bc_eval_llm = ModuleType("bc_eval.llm")
    bc_eval_llm.llm_api = SimpleNamespace(create_llm_api_client=create_client)
    bc_eval.llm = bc_eval_llm
    monkeypatch.setitem(sys.modules, "bc_eval", bc_eval)
    monkeypatch.setitem(sys.modules, "bc_eval.llm", bc_eval_llm)

    install_sticky_route_compat()
    compatible_client = bc_eval_llm.llm_api.create_llm_api_client()

    assert compatible_client.chat.completions.create(model="gpt") == {"id": "first"}
    assert compatible_client.chat.completions.create(model="gpt") == {"id": "second"}
    assert completions.requests == [
        {"model": "gpt"},
        {"model": "gpt", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: "secret-ticket"}},
        {"model": "gpt", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: "secret-ticket"}},
    ]


def test_sticky_route_session_retries_with_response_ticket_and_reuses_it():
    completions = _Completions([_ticket_required("secret-ticket"), {"id": "first"}, {"id": "second"}])
    session = StickyRouteSession()

    assert session.create(completions, {"model": "gpt-55-chat"}) == {"id": "first"}
    assert session.create(completions, {"model": "gpt-55-chat"}) == {"id": "second"}
    assert _STICKY_ROUTE_TICKET_HEADER not in completions.requests[0].get("extra_headers", {})
    assert completions.requests[1]["extra_headers"] == {_STICKY_ROUTE_TICKET_HEADER: "secret-ticket"}
    assert completions.requests[2]["extra_headers"] == {_STICKY_ROUTE_TICKET_HEADER: "secret-ticket"}


def test_sticky_route_session_fails_closed_when_service_returns_no_ticket():
    session = StickyRouteSession()

    with pytest.raises(RuntimeError, match="did not return one for retry") as raised:
        session.create(_Completions([_ticket_required()]), {"model": "gpt-55-chat"})

    assert "secret" not in str(raised.value)


def test_sticky_route_session_does_not_handle_unrelated_bad_request():
    session = StickyRouteSession()
    error = _ServiceError("Invalid taxonomy agent.")

    with pytest.raises(_ServiceError) as raised:
        session.create(_Completions([error]), {"model": "gpt-55-chat"})

    assert raised.value is error


def test_sticky_route_session_suppresses_rejected_ticket_value():
    completions = _Completions([_ticket_required("secret-ticket"), _ServiceError("invalid ticket: secret-ticket")])
    session = StickyRouteSession()

    with pytest.raises(RuntimeError, match="rejected its response-derived") as raised:
        session.create(completions, {"model": "gpt-55-chat"})

    assert "secret-ticket" not in str(raised.value)
