from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from bcbench.agent.bcal.bc_eval_llm_api_bridge import (
    _STICKY_ROUTE_TICKET_HEADER,
    StickyRouteSession,
    install_sticky_route_compat,
    sticky_route_ticket_broker_environment,
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
    bc_eval_llm.llm_api = SimpleNamespace(create_llm_api_client=create_client)  # ty: ignore[unresolved-attribute]
    bc_eval.llm = bc_eval_llm  # ty: ignore[unresolved-attribute]
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


def test_external_bridge_replays_ticket_across_process_turns(tmp_path: Path):
    package = tmp_path / "bc_eval" / "llm"
    package.mkdir(parents=True)
    (tmp_path / "bc_eval" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "llm_api.py").write_text(
        dedent(
            f"""
            import json
            import os

            TICKET_HEADER = {_STICKY_ROUTE_TICKET_HEADER!r}


            class LlmApiSettings:
                tenant_id = ""
                client_id = ""

                @classmethod
                def from_env(cls):
                    return cls()


            class RawResponse:
                headers = {{TICKET_HEADER: "opaque-ticket"}}

                def parse(self):
                    return {{"choices": [{{"message": {{"content": "READY"}}}}]}}


            class RawCompletions:
                def create(self, **kwargs):
                    ticket = kwargs["extra_headers"][TICKET_HEADER]
                    with open(os.environ["REQUEST_LOG"], "a", encoding="utf-8") as stream:
                        stream.write(json.dumps({{"ticket": ticket}}) + "\\n")
                    if ticket not in {{"", "opaque-ticket"}}:
                        raise RuntimeError("unexpected ticket")
                    return RawResponse()


            class Completions:
                def __init__(self):
                    self.with_raw_response = RawCompletions()


            class Client:
                def __init__(self):
                    self.chat = type("Chat", (), {{"completions": Completions()}})()


            def create_llm_api_client(**kwargs):
                return Client()
            """
        ),
        encoding="utf-8",
    )
    bridge = Path(__file__).parents[1] / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_llm_api_bridge.py"
    request_log = tmp_path / "requests.jsonl"
    request = json.dumps({"model": "gpt-55-chat", "messages": [{"role": "user", "content": "READY"}]})

    with sticky_route_ticket_broker_environment() as broker_environment:
        environment = (
            os.environ
            | broker_environment
            | {
                "PYTHONPATH": str(tmp_path),
                "REQUEST_LOG": str(request_log),
            }
        )
        turns = [
            subprocess.run(
                [sys.executable, str(bridge)],
                input=request,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=environment,
                check=False,
            )
            for _ in range(2)
        ]

    assert [turn.returncode for turn in turns] == [0, 0]
    assert [json.loads(line)["ticket"] for line in request_log.read_text(encoding="utf-8").splitlines()] == ["", "opaque-ticket"]
    assert all("opaque-ticket" not in turn.stdout + turn.stderr for turn in turns)


def test_external_bridge_fails_without_session_broker(tmp_path: Path):
    package = tmp_path / "bc_eval" / "llm"
    package.mkdir(parents=True)
    (tmp_path / "bc_eval" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "llm_api.py").write_text(
        dedent(
            """
            class LlmApiSettings:
                tenant_id = ""
                client_id = ""

                @classmethod
                def from_env(cls):
                    return cls()


            def create_llm_api_client(**kwargs):
                return type("Client", (), {"chat": type("Chat", (), {"completions": object()})()})()
            """
        ),
        encoding="utf-8",
    )
    bridge = Path(__file__).parents[1] / "src" / "bcbench" / "agent" / "bcal" / "bc_eval_llm_api_bridge.py"
    environment = os.environ | {"PYTHONPATH": str(tmp_path)}
    for name in (
        "BCBENCH_STICKY_ROUTE_BROKER_ADDRESS",
        "BCBENCH_STICKY_ROUTE_BROKER_AUTH",
        "BCBENCH_STICKY_ROUTE_BROKER_FAMILY",
    ):
        environment.pop(name, None)

    completed = subprocess.run(
        [sys.executable, str(bridge)],
        input=json.dumps({"model": "gpt-55-chat", "messages": []}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )

    assert completed.returncode != 0
    assert "requires a session-scoped sticky-route broker" in completed.stderr
