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


class TestNL2ALRunAgentEmptyDiffRetry:
    def _run(self, tmp_path, monkeypatch, diff_side_effects):
        ctx = _nl2al_context(tmp_path)
        pipeline = NL2ALPipeline()

        agent_calls = {"n": 0}

        def agent_runner(_ctx):
            agent_calls["n"] += 1
            return (None, None)

        reset_calls = {"n": 0}
        monkeypatch.setattr(pipeline, "setup_workspace", lambda *_args, **_kw: reset_calls.__setitem__("n", reset_calls["n"] + 1))

        calls = {"n": 0}

        def fake_stage(_repo_path):
            i = calls["n"]
            calls["n"] += 1
            effect = diff_side_effects[i]
            if isinstance(effect, Exception):
                raise effect
            return effect

        monkeypatch.setattr("bcbench.evaluate.nl2al.stage_and_get_diff", fake_stage)
        pipeline.run_agent(ctx, agent_runner)
        return agent_calls["n"], reset_calls["n"]

    def test_no_retry_when_first_diff_non_empty(self, tmp_path, monkeypatch):
        agent_n, reset_n = self._run(tmp_path, monkeypatch, ["diff --git a/x.al b/x.al"])
        assert agent_n == 1
        assert reset_n == 0

    def test_retries_then_succeeds(self, tmp_path, monkeypatch):
        agent_n, reset_n = self._run(tmp_path, monkeypatch, [EmptyDiffError(), "diff --git a/x.al b/x.al"])
        assert agent_n == 2
        assert reset_n == 1

    def test_stops_after_max_attempts_all_empty(self, tmp_path, monkeypatch):
        from bcbench.evaluate.nl2al import _EMPTY_DIFF_MAX_ATTEMPTS

        # One fewer stage check than attempts (last attempt is accepted without a check).
        agent_n, reset_n = self._run(tmp_path, monkeypatch, [EmptyDiffError()] * (_EMPTY_DIFF_MAX_ATTEMPTS - 1))
        assert agent_n == _EMPTY_DIFF_MAX_ATTEMPTS
        assert reset_n == _EMPTY_DIFF_MAX_ATTEMPTS - 1
