"""Tests for NL2ALPipeline.evaluate() — empty-diff handling is nl2al-specific."""

import pytest

from bcbench.config import get_config
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.exceptions import EmptyDiffError
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationCategory
from tests.conftest import create_evaluation_context, create_nl2al_entry


def _read_only_result(ctx) -> JudgeBasedEvaluationResult:
    result_file = ctx.result_dir / f"{ctx.entry.instance_id}{get_config().file_patterns.result_pattern}"
    lines = result_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1, f"Expected one persisted result, got {len(lines)}: {lines}"
    return JudgeBasedEvaluationResult.model_validate_json(lines[0])


def _nl2al_context(tmp_path):
    entry = create_nl2al_entry()
    return create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)  # ty: ignore[invalid-argument-type]


class TestNL2ALEvaluateEmptyDiff:
    def test_empty_diff_persists_failure_and_does_not_raise(self, tmp_path, monkeypatch):
        ctx = _nl2al_context(tmp_path)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", lambda _repo_path: (_ for _ in ()).throw(EmptyDiffError()))

        NL2ALPipeline().evaluate(ctx)

        result = _read_only_result(ctx)
        assert result.output == ""
        assert result.error_message is None
        assert result.timeout is False

    def test_non_empty_diff_persists_raw_output(self, tmp_path, monkeypatch):
        ctx = _nl2al_context(tmp_path)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", lambda _repo_path: "diff --git a/x.al b/x.al\n+pageextension")

        NL2ALPipeline().evaluate(ctx)

        result = _read_only_result(ctx)
        assert result.error_message is None
        assert "pageextension" in result.output

    def test_unexpected_exceptions_still_propagate(self, tmp_path, monkeypatch):
        ctx = _nl2al_context(tmp_path)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", lambda _repo_path: (_ for _ in ()).throw(RuntimeError("infra blew up")))

        with pytest.raises(RuntimeError, match="infra blew up"):
            NL2ALPipeline().evaluate(ctx)
