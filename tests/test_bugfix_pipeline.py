from bcbench.config import get_config
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.exceptions import EmptyDiffError
from bcbench.results.bugfix import BugFixResult
from tests.conftest import create_evaluation_context


def test_empty_diff_is_persisted_as_failed_result(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    monkeypatch.setattr("bcbench.evaluate.bugfix.clean_project_paths", lambda *_args: None)
    monkeypatch.setattr("bcbench.evaluate.bugfix.stage_and_get_diff", lambda _repo_path: (_ for _ in ()).throw(EmptyDiffError()))

    BugFixPipeline().evaluate(context)

    result_file = context.result_dir / f"{context.entry.instance_id}{get_config().file_patterns.result_pattern}"
    result = BugFixResult.model_validate_json(result_file.read_text(encoding="utf-8"))
    assert result.output == ""
    assert result.resolved is False
    assert result.build is False
    assert result.error_message == "Generated diff is empty. Agent did not make any changes."
