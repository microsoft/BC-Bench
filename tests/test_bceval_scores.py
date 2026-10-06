from __future__ import annotations

import sys
import types
from typing import cast

import pytest

from evaluator import scores


@pytest.mark.parametrize(
    ("model", "expected_content"),
    [
        (
            "gpt-56-reasoning-nano-luna",
            [{"type": "output_text", "text": "answer"}],
        ),
        ("gpt-41-2025-04-14", "answer"),
    ],
)
def test_lm_checklist_uses_output_text_only_for_responses_models(monkeypatch, model, expected_content):
    class _BuiltInLmChecklist:
        def _request_args(self, output, expected, **kwargs):
            return {
                "model": model,
                "messages": [
                    {"role": "system", "content": "instructions"},
                    {"role": "user", "content": "question"},
                    {"role": "assistant", "content": output},
                ],
            }

    module = types.ModuleType("bc_eval.scorers.autoeval.lmchecklist")
    module.LmChecklist = _BuiltInLmChecklist  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    scorer = cast(_BuiltInLmChecklist, scores.LmChecklist())
    request = scorer._request_args("answer", {"assertions": []})

    assert isinstance(scorer, _BuiltInLmChecklist)
    assert request["messages"] == [
        {"role": "system", "content": "instructions"},
        {"role": "user", "content": "question"},
        {
            "role": "assistant",
            "content": expected_content,
        },
    ]
