from typing import override
from unittest.mock import MagicMock

import pytest
from bcbench_core.agent.harness import AgentRequest, AgentResult
from bcbench_core.evaluation import evaluate_task
from bcbench_core.exceptions import AgentTimeoutError

from bcbench.categories.ext_request_advisor import ADVISOR_RESULT_FILE, DEFINITION, ExtRequestAdvisorCategory, ExtRequestAdvisorEntry
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationCategory, EvaluationContext
from tests.conftest import StubHarness, create_evaluation_context, create_ext_advisor_entry

CATEGORY = EvaluationCategory.EXT_REQUEST_ADVISOR


def _advisor_context(tmp_path) -> EvaluationContext[ExtRequestAdvisorEntry]:
    return create_evaluation_context(tmp_path, entry=create_ext_advisor_entry(), category=CATEGORY)


CATEGORY_IMPL = ExtRequestAdvisorCategory()


def test_empty_advisor_output_is_kept_as_empty_output(tmp_path):
    result = CATEGORY_IMPL.grade(_advisor_context(tmp_path), AgentResult())

    assert result.output == ""
    assert result.error_message is None


def test_advisor_json_is_kept_as_raw_output(tmp_path):
    output = '{"classification":{"type":"event-request","subtype":"regular"}}'
    context = _advisor_context(tmp_path)
    context.repo_path.mkdir()
    (context.repo_path / ADVISOR_RESULT_FILE).write_text(output, encoding="utf-8")

    result = CATEGORY_IMPL.grade(context, AgentResult())

    assert result.output == output
    assert result.category == CATEGORY


def test_prepare_removes_stale_advisor_output(tmp_path, monkeypatch):
    context = _advisor_context(tmp_path)
    context.repo_path.mkdir()
    result_path = context.repo_path / ADVISOR_RESULT_FILE
    result_path.write_text("stale", encoding="utf-8")
    monkeypatch.setattr("bcbench.categories.ext_request_advisor.setup_repo_prebuild", lambda *_args: None)

    CATEGORY_IMPL.prepare(context)

    assert not result_path.exists()


class TestEvaluateTask:
    @pytest.fixture(autouse=True)
    def _skip_repo_setup(self, monkeypatch):
        monkeypatch.setattr("bcbench.categories.ext_request_advisor.setup_repo_prebuild", lambda _entry, repo_path: repo_path.mkdir(parents=True, exist_ok=True))

    def test_grades_the_agent_output(self, tmp_path):
        context = _advisor_context(tmp_path)
        output = '{"classification":{"type":"event-request"}}'

        class WritingHarness(StubHarness[ExtRequestAdvisorEntry]):
            @override
            def run(self, request: AgentRequest[ExtRequestAdvisorEntry], /) -> AgentResult:
                (request.work_dir / ADVISOR_RESULT_FILE).write_text(output, encoding="utf-8")
                return AgentResult()

        result = evaluate_task(CATEGORY_IMPL, context, WritingHarness(), context.agent_request(), on_timeout=DEFINITION.timeout_result)

        assert isinstance(result, JudgeBasedEvaluationResult)
        assert (result.category, result.output, result.timeout) == (CATEGORY, output, False)
        assert result.judge_model == CATEGORY.judge_model

    def test_timeout_creates_a_timeout_result(self, tmp_path):
        context = _advisor_context(tmp_path)
        harness = MagicMock(spec=StubHarness)
        harness.run.side_effect = AgentTimeoutError("too slow")

        result = evaluate_task(CATEGORY_IMPL, context, harness, context.agent_request(), on_timeout=DEFINITION.timeout_result)

        assert isinstance(result, JudgeBasedEvaluationResult)
        assert (result.timeout, result.error_message) == (True, "Agent timed out")
        assert result.judge_model == CATEGORY.judge_model
