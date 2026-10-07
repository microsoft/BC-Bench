from __future__ import annotations

import json
import sys
import types
from typing import cast

import pytest

from evaluator import scores


class _RecordingClient:
    def __init__(self, *, responses_result=None, chat_result=None):
        self.responses_result = responses_result
        self.chat_result = chat_result
        self.responses_calls = []
        self.chat_calls = []
        self.openai = types.SimpleNamespace(responses=types.SimpleNamespace(create=self._create_response))

    def _create_response(self, **kwargs):
        self.responses_calls.append(kwargs)
        return self.responses_result

    def complete(self, **kwargs):
        self.chat_calls.append(kwargs)
        if self.chat_result is None:
            raise AssertionError("Chat completions should not be used")
        return self.chat_result


class _ModelResponse:
    def __init__(self, data):
        self.output = data["output"]
        self._data = data

    def model_dump(self):
        return self._data


def _install_lm_checklist_dependencies(monkeypatch, *, model, client):
    class _BuiltInLmChecklist:
        def __init__(self):
            self.client = client
            self.extra_args = {}

        def _request_args(self, output, expected, **kwargs):
            return {
                "client": self.client,
                "model": model,
                "temperature": 0,
                "max_tokens": 4096,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": "instructions"},
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": output},
                ],
            }

        def _process_response(self, response, assertions):
            evaluated = json.loads(response["choices"][0]["message"]["content"])["assertions"]
            passed = all(
                next(
                    (result["pass"] for result in evaluated if result["text"] == assertion["text"]),
                    False,
                )
                for assertion in assertions
            )
            return [
                types.SimpleNamespace(name="pass_rate", score=float(passed)),
                types.SimpleNamespace(name="test_passed", score=float(passed)),
            ]

        def _run_eval_sync(self, output, expected, **kwargs):
            request = self._request_args(output, expected, **kwargs)
            request_client = prepare_openai(client=request.pop("client"))
            response = request_client.complete(**request)
            return self._process_response(response, expected["assertions"])

    def prepare_openai(*, client=None, is_async=False):
        assert not is_async
        return client or _RecordingClient()

    bc_eval_module = types.ModuleType("bc_eval.scorers.autoeval.lmchecklist")
    bc_eval_module.LmChecklist = _BuiltInLmChecklist  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, bc_eval_module.__name__, bc_eval_module)

    autoevals_module = types.ModuleType("autoevals.oai")
    autoevals_module.prepare_openai = prepare_openai  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, autoevals_module.__name__, autoevals_module)
    return _BuiltInLmChecklist


@pytest.mark.parametrize(
    ("model", "expected_content", "expects_temperature", "adapts_client"),
    [
        (
            "gpt-56-reasoning-nano-luna",
            [{"type": "output_text", "text": "answer"}],
            False,
            True,
        ),
        (
            "gpt-5-mini",
            [{"type": "output_text", "text": "answer"}],
            True,
            False,
        ),
        ("gpt-41-2025-04-14", "answer", True, False),
    ],
)
def test_lm_checklist_adapts_only_luna_responses_payload(
    monkeypatch,
    model,
    expected_content,
    expects_temperature,
    adapts_client,
):
    client = _RecordingClient()
    built_in = _install_lm_checklist_dependencies(monkeypatch, model=model, client=client)

    scorer = cast(built_in, scores.LmChecklist())
    request = scorer._request_args("answer", {"assertions": []})

    assert isinstance(scorer, built_in)
    assert request["messages"] == [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": expected_content,
        },
    ]
    assert ("temperature" in request) is expects_temperature
    assert (request["client"] is not client) is adapts_client


def test_lm_checklist_parses_nested_luna_response(monkeypatch):
    assertion = {"text": "The answer is correct.", "level": "critical"}
    judgment = {
        "assertions": [
            {
                "text": assertion["text"],
                "reasoning": "The response matches.",
                "pass": True,
            }
        ]
    }
    client = _RecordingClient(
        responses_result=_ModelResponse(
            {
                "id": "resp-1",
                "object": "response",
                "created_at": 123,
                "model": "gpt-56-reasoning-nano-luna",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(judgment),
                            }
                        ],
                    }
                ],
            }
        )
    )
    built_in = _install_lm_checklist_dependencies(
        monkeypatch,
        model="gpt-56-reasoning-nano-luna",
        client=client,
    )

    scorer = cast(built_in, scores.LmChecklist())
    result = scorer._run_eval_sync(
        "answer",
        {"assertions": [assertion]},
        input="question",
    )

    assert {score.name: score.score for score in result} == {
        "pass_rate": 1.0,
        "test_passed": 1.0,
    }
    assert len(client.responses_calls) == 1
    responses_request = client.responses_calls[0]
    assert responses_request["model"] == "gpt-56-reasoning-nano-luna"
    assert responses_request["max_output_tokens"] == 4096
    assert responses_request["text"] == {"format": {"type": "json_object"}}
    assert responses_request["input"][-1] == {
        "role": "assistant",
        "content": [{"type": "output_text", "text": "answer"}],
    }
    assert "max_tokens" not in responses_request
    assert "response_format" not in responses_request
    assert "temperature" not in responses_request
    assert client.chat_calls == []


def test_lm_checklist_delegates_non_luna_requests(monkeypatch):
    assertion = {"text": "The answer is correct."}
    client = _RecordingClient(
        chat_result={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "assertions": [
                                    {
                                        "text": assertion["text"],
                                        "reasoning": "The response matches.",
                                        "pass": True,
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
    )
    built_in = _install_lm_checklist_dependencies(
        monkeypatch,
        model="gpt-5-mini",
        client=client,
    )

    scorer = cast(built_in, scores.LmChecklist())
    result = scorer._run_eval_sync("answer", {"assertions": [assertion]})

    assert {score.name: score.score for score in result}["test_passed"] == 1.0
    assert len(client.chat_calls) == 1
    assert client.responses_calls == []


def test_lm_checklist_rejects_luna_response_without_output_text(monkeypatch):
    client = _RecordingClient(
        responses_result={
            "id": "resp-1",
            "object": "response",
            "model": "gpt-56-reasoning-nano-luna",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                }
            ],
        }
    )
    built_in = _install_lm_checklist_dependencies(
        monkeypatch,
        model="gpt-56-reasoning-nano-luna",
        client=client,
    )

    scorer = cast(built_in, scores.LmChecklist())

    with pytest.raises(
        ValueError,
        match="Luna Responses API response contained no assistant output_text content",
    ):
        scorer._run_eval_sync(
            "answer",
            {"assertions": [{"text": "The answer is correct."}]},
        )
