from bcbench.config import get_config
from bcbench.evaluate.ext_request_advisor import ADVISOR_RESULT_FILE, ExtRequestAdvisorPipeline
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationCategory
from tests.conftest import create_evaluation_context, create_ext_advisor_entry


def _advisor_context(tmp_path):
    return create_evaluation_context(
        tmp_path,
        entry=create_ext_advisor_entry(),
        category=EvaluationCategory.EXT_REQUEST_ADVISOR,
    )


def _read_result(context) -> JudgeBasedEvaluationResult:
    result_file = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    return JudgeBasedEvaluationResult.model_validate_json(result_file.read_text(encoding="utf-8").strip())


def test_empty_advisor_output_persists_failure(tmp_path):
    context = _advisor_context(tmp_path)

    ExtRequestAdvisorPipeline().evaluate(context)

    assert _read_result(context).output == ""


def test_advisor_json_persists_as_raw_output(tmp_path):
    context = _advisor_context(tmp_path)
    output = '{"classification":{"type":"event-request","subtype":"regular"}}'
    context.repo_path.mkdir()
    (context.repo_path / ADVISOR_RESULT_FILE).write_text(output, encoding="utf-8")

    ExtRequestAdvisorPipeline().evaluate(context)

    assert _read_result(context).output == output


def test_setup_removes_stale_advisor_output(tmp_path, monkeypatch):
    context = _advisor_context(tmp_path)
    result_path = context.repo_path / ADVISOR_RESULT_FILE
    context.repo_path.mkdir()
    result_path.write_text("stale", encoding="utf-8")
    monkeypatch.setattr("bcbench.evaluate.ext_request_advisor.setup_repo_prebuild", lambda *_args: None)

    ExtRequestAdvisorPipeline().setup(context)

    assert not result_path.exists()
