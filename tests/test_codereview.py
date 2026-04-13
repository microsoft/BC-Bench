import json

from bcbench.dataset import CodeReviewEntry
from bcbench.dataset.codereview import ReviewComment
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.codereview import CodeReviewResult
from bcbench.types import EvaluationCategory
from tests.conftest import create_codereview_entry, create_codereview_result, create_evaluation_context


class TestCodeReviewEntry:
    def test_get_task_returns_patch(self):
        entry = create_codereview_entry(patch="diff --git a/test.al b/test.al\n+new line")
        assert entry.get_task() == "diff --git a/test.al b/test.al\n+new line"

    def test_get_expected_output_formats_comments(self):
        comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix this", severity="warning"),
            ReviewComment(file="src/app.al", line_start=20, body="Consider that", severity="suggestion"),
        ]
        entry = create_codereview_entry(expected_comments=comments)
        output = entry.get_expected_output()
        assert "[warning] src/app.al:10: Fix this" in output
        assert "[suggestion] src/app.al:20: Consider that" in output

    def test_entry_does_not_require_test_fields(self):
        entry = create_codereview_entry()
        assert not hasattr(entry, "fail_to_pass")
        assert not hasattr(entry, "test_patch")

    def test_load_from_jsonl(self, tmp_path):
        entry = create_codereview_entry()
        dataset_path = tmp_path / "codereview.jsonl"
        entry.save_to_file(dataset_path)

        loaded = CodeReviewEntry.load(dataset_path)
        assert len(loaded) == 1
        assert loaded[0].instance_id == entry.instance_id
        assert len(loaded[0].expected_comments) == len(entry.expected_comments)

    def test_empty_expected_comments_is_valid(self):
        entry = create_codereview_entry(expected_comments=[])
        assert entry.expected_comments == []
        assert entry.get_expected_output() == ""


class TestCodeReviewResult:
    def test_create_result(self):
        result = create_codereview_result()
        assert result.category == EvaluationCategory.CODE_REVIEW
        assert len(result.generated_comments) == 1

    def test_round_trip_serialization(self, tmp_path):
        output = json.dumps([{"file": "test.al", "line_start": 5, "body": "Good catch"}])
        original = create_codereview_result(
            instance_id="codereview-round-trip",
            output=output,
        )

        original.save(tmp_path, "test.jsonl")

        with open(tmp_path / "test.jsonl") as f:
            data = json.loads(f.readline())

        loaded = BaseEvaluationResult.from_json(data)
        assert isinstance(loaded, CodeReviewResult)
        assert loaded.category == EvaluationCategory.CODE_REVIEW
        assert len(loaded.generated_comments) == 1

    def test_category_loads_from_string(self):
        payload = {
            "instance_id": "test__instance",
            "project": "app",
            "model": "gpt-4o",
            "agent_name": "copilot-cli",
            "category": "code-review",
            "output": "",
        }

        result = BaseEvaluationResult.from_json(payload)
        assert result.category == EvaluationCategory.CODE_REVIEW
        assert isinstance(result, CodeReviewResult)


class TestCodeReviewPipeline:
    def test_pipeline_instantiates(self):
        pipeline = EvaluationCategory.CODE_REVIEW.pipeline
        assert pipeline is not None

    def test_entry_class_is_codereview(self):
        assert EvaluationCategory.CODE_REVIEW.entry_class == CodeReviewEntry

    def test_context_does_not_require_container(self, tmp_path):
        entry = create_codereview_entry()
        context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.CODE_REVIEW)
        # Container is passed but pipeline doesn't use it — this is fine
        assert context.category == EvaluationCategory.CODE_REVIEW
