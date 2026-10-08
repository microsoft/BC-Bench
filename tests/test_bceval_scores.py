from __future__ import annotations

import sys
import types
from typing import cast

from evaluator import scores


class _Score:
    def __init__(self, *, name, score, metadata):
        self.name = name
        self.score = score
        self.metadata = metadata


def _install_lm_checklist_dependencies(monkeypatch):
    class _BuiltInLmChecklist:
        def __init__(self):
            self.calls = []

        def _run_eval_sync(self, output, expected, **kwargs):
            self.calls.append((output, expected, kwargs))
            return [_Score(name="test_passed", score=1.0, metadata={})]

        @staticmethod
        def _rate(assertions, level=None):
            selected = [assertion for assertion in assertions if level is None or assertion.get("level") == level]
            if not selected:
                return 0.0
            return sum(1 for assertion in selected if assertion["pass"]) / len(selected)

    bc_eval_module = types.ModuleType("bc_eval.scorers.autoeval.lmchecklist")
    bc_eval_module.LmChecklist = _BuiltInLmChecklist  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, bc_eval_module.__name__, bc_eval_module)

    autoevals_module = types.ModuleType("autoevals")
    autoevals_module.Score = _Score  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, autoevals_module.__name__, autoevals_module)
    return _BuiltInLmChecklist


def test_lm_checklist_delegates_normal_results_and_selects_row_core_score(monkeypatch):
    built_in = _install_lm_checklist_dependencies(monkeypatch)
    scorer = cast(built_in, scores.LmChecklist())
    metadata = {}

    result = scorer._run_eval_sync("answer", {"assertions": []}, metadata=metadata)

    assert {score.name: score.score for score in result} == {"test_passed": 1.0}
    assert metadata["core_score_name"] == "test_passed"
    assert len(scorer.calls) == 1


def test_lm_checklist_scores_timeout_without_calling_judge(monkeypatch):
    built_in = _install_lm_checklist_dependencies(monkeypatch)
    metadata = {"timeout": True}
    assertions = [
        {"text": "Critical behavior.", "level": "critical"},
        {"text": "Expected behavior.", "level": "expected"},
    ]

    scorer = cast(built_in, scores.LmChecklist())
    result = scorer._run_eval_sync("", {"assertions": assertions}, metadata=metadata)

    assert {score.name: score.score for score in result} == {
        "pass_rate": 0.0,
        "critical_pass_rate": 0.0,
        "expected_pass_rate": 0.0,
        "aspirational_pass_rate": 0.0,
        "test_passed": 0.0,
    }
    assert scorer.calls == []
    assert metadata["core_score_name"] == "test_passed"
    assert metadata["assertionResults"] == [{**assertion, "pass": False, "reasoning": "Agent timed out before producing output"} for assertion in assertions]


def test_lm_checklist_skips_infrastructure_error_without_calling_judge(monkeypatch):
    built_in = _install_lm_checklist_dependencies(monkeypatch)
    error_message = "LLM API infrastructure error (HTTP 500): DependencyFailure"
    metadata = {
        "infrastructure_error": True,
        "Error": error_message,
    }

    scorer = cast(built_in, scores.LmChecklist())
    result = scorer._run_eval_sync(
        "",
        {"assertions": [{"text": "Critical behavior.", "level": "critical"}]},
        metadata=metadata,
    )

    assert {score.name: score.score for score in result} == {
        "pass_rate": None,
        "critical_pass_rate": None,
        "expected_pass_rate": None,
        "aspirational_pass_rate": None,
        "test_passed": None,
    }
    assert all(score.metadata == {"error": error_message} for score in result)
    assert metadata["core_score_name"] == "test_passed"
    assert scorer.calls == []
