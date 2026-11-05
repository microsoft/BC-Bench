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
class _RawResponse:
    value: object
    headers: dict[str, str]

    def parse(self) -> object:
        return self.value


class _RawCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(value: object, ticket: str | None = None) -> _RawResponse:
    headers = {_STICKY_ROUTE_TICKET_HEADER: ticket} if ticket is not None else {}
    return _RawResponse(value, headers)


def test_install_compat_wraps_initial_and_subsequent_requests(monkeypatch: pytest.MonkeyPatch):
    raw_completions = _RawCompletions([_response({"id": "first"}, "secret-ticket"), _response({"id": "second"}, "updated-ticket")])
    completions = SimpleNamespace(
        create=lambda **kwargs: None,
        with_raw_response=SimpleNamespace(create=raw_completions.create),
    )
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
    assert raw_completions.requests == [
        {"model": "gpt", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: ""}},
        {"model": "gpt", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: "secret-ticket"}},
    ]


def test_sticky_route_session_caches_tickets_per_model():
    completions = _RawCompletions(
        [
            _response({"id": "first"}, "ticket-a"),
            _response({"id": "other"}, "ticket-b"),
            _response({"id": "second"}, "ticket-a2"),
        ]
    )
    session = StickyRouteSession()

    assert session.create(completions, {"model": "model-a"}) == {"id": "first"}
    assert session.create(completions, {"model": "model-b"}) == {"id": "other"}
    assert session.create(completions, {"model": "model-a"}) == {"id": "second"}
    assert completions.requests == [
        {"model": "model-a", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: ""}},
        {"model": "model-b", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: ""}},
        {"model": "model-a", "extra_headers": {_STICKY_ROUTE_TICKET_HEADER: "ticket-a"}},
    ]


def test_sticky_route_session_defaults_missing_response_ticket_to_empty():
    completions = _RawCompletions([_response({"id": "first"}), _response({"id": "second"})])
    session = StickyRouteSession()

    session.create(completions, {"model": "gpt-55-chat"})
    session.create(completions, {"model": "gpt-55-chat"})

    assert completions.requests[0]["extra_headers"] == {_STICKY_ROUTE_TICKET_HEADER: ""}
    assert completions.requests[1]["extra_headers"] == {_STICKY_ROUTE_TICKET_HEADER: ""}


def test_sticky_route_session_preserves_other_request_headers():
    completions = _RawCompletions([_response({"id": "first"})])

    StickyRouteSession().create(
        completions,
        {"model": "gpt-55-chat", "extra_headers": {"x-existing": "value"}},
    )

    assert completions.requests[0]["extra_headers"] == {
        "x-existing": "value",
        _STICKY_ROUTE_TICKET_HEADER: "",
    }


def test_sticky_route_session_does_not_handle_unrelated_taxonomy_error():
    error = ValueError("Invalid taxonomy agent.")
    session = StickyRouteSession()

    with pytest.raises(ValueError, match="Invalid taxonomy agent") as raised:
        session.create(_RawCompletions([error]), {"model": "gpt-55-chat"})

    assert raised.value is error


def test_sticky_route_session_suppresses_rejected_ticket_value():
    completions = _RawCompletions([_response({"id": "first"}, "secret-ticket"), RuntimeError("invalid ticket: secret-ticket")])
    session = StickyRouteSession()
    session.create(completions, {"model": "gpt-55-chat"})

    with pytest.raises(RuntimeError, match="rejected its response-derived") as raised:
        session.create(completions, {"model": "gpt-55-chat"})

    assert "secret-ticket" not in str(raised.value)


def test_sticky_route_session_requires_model():
    with pytest.raises(TypeError, match="string model"):
        StickyRouteSession().create(_RawCompletions([]), {})
