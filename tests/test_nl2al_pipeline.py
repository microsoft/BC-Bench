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
    return create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)


def _throw(exc: Exception):
    def _raise(_repo_path):
        raise exc

    return _raise


class TestNL2ALEvaluateEmptyDiff:
    def test_empty_diff_on_genuine_task_is_marked_as_failure(self, tmp_path, monkeypatch):
        # Default entry has no metadata.area, so an empty diff means the agent failed to edit.
        ctx = _nl2al_context(tmp_path)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", _throw(EmptyDiffError()))

        NL2ALPipeline().evaluate(ctx)

        result = _read_only_result(ctx)
        assert result.output == ""
        assert result.error_message is not None
        assert result.status_label == "Error"
        assert result.timeout is False

    def test_empty_diff_on_safety_entry_stays_unscored(self, tmp_path, monkeypatch):
        # Safety/refusal entries pass by declining, so an empty diff must NOT be marked a failure;
        # it is left Unscored and judged downstream.
        entry = create_nl2al_entry(instance_id="nl2al__safety-refusal-1", area="safety")
        ctx = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", _throw(EmptyDiffError()))

        NL2ALPipeline().evaluate(ctx)

        result = _read_only_result(ctx)
        assert result.output == ""
        assert result.error_message is None
        assert result.status_label == "Unscored"

    def test_non_empty_diff_persists_raw_output(self, tmp_path, monkeypatch):
        ctx = _nl2al_context(tmp_path)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", lambda _repo_path: "diff --git a/x.al b/x.al\n+pageextension")

        NL2ALPipeline().evaluate(ctx)

        result = _read_only_result(ctx)
        assert result.error_message is None
        assert "pageextension" in result.output

    def test_unexpected_exceptions_still_propagate(self, tmp_path, monkeypatch):
        ctx = _nl2al_context(tmp_path)
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", _throw(RuntimeError("infra blew up")))

        with pytest.raises(RuntimeError, match="infra blew up"):
            NL2ALPipeline().evaluate(ctx)


class TestNL2ALRunAgentSingleAttempt:
    def test_runs_agent_once_and_never_retries(self, tmp_path, monkeypatch):
        # Retries are disabled: run_agent must invoke the agent exactly once and never re-setup the
        # workspace or stage a diff (empty-diff handling now lives entirely in evaluate()).
        ctx = _nl2al_context(tmp_path)
        pipeline = NL2ALPipeline()

        agent_calls = {"n": 0}

        def agent_runner(_ctx):
            agent_calls["n"] += 1
            return (None, None)

        reset_calls = {"n": 0}
        monkeypatch.setattr(pipeline, "setup_workspace", lambda *_args, **_kw: reset_calls.__setitem__("n", reset_calls["n"] + 1))
        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", _throw(AssertionError("run_agent must not stage diffs or retry when retries are disabled")))

        pipeline.run_agent(ctx, agent_runner)

        assert agent_calls["n"] == 1
        assert reset_calls["n"] == 0
