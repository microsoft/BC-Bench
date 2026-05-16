import json

from bcbench.dataset import CodeReviewEntry
from bcbench.dataset.codereview import ReviewComment
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.codereview import CodeReviewResult
from bcbench.results.summary import CodeReviewResultSummary
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

    def test_parses_skill_style_output_schema(self):
        output = json.dumps(
            {
                "findings": [
                    {
                        "filePath": "src/app.al",
                        "lineNumber": 12,
                        "severity": "High",
                        "issue": "Potential SQL injection risk",
                        "recommendation": "Use parameterized queries",
                        "suggestedCode": "DoSafeThing();",
                    }
                ]
            }
        )

        result = create_codereview_result(output=output)

        assert result.valid_review_output is True
        assert len(result.generated_comments) == 1
        assert result.generated_comments[0].file == "src/app.al"
        assert result.generated_comments[0].line_start == 12
        assert result.generated_comments[0].body == "Potential SQL injection risk"

    def test_metrics_match_expected_comments_with_tolerance(self):
        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity="warning"),
            ReviewComment(file="src/app.al", line_start=40, body="Validate input", severity="high"),
        ]
        generated_output = json.dumps(
            [
                {
                    "file": "src/app.al",
                    "line_start": 12,
                    "body": "Potential null reference",
                    "severity": "warning",
                },
                {
                    "file": "src/other.al",
                    "line_start": 99,
                    "body": "Unrelated finding",
                    "severity": "low",
                },
            ]
        )

        result = create_codereview_result(output=generated_output, expected_comments=expected_comments, line_tolerance=5)

        assert result.matched_comment_count == 1
        assert result.missed_comment_count == 1
        assert result.incorrect_comment_count == 1
        assert result.precision == 0.5
        assert result.recall == 0.5
        assert result.f1 == 0.5
        assert result.severity_mae == 0.0

    def test_severity_aliases_normalize_to_skill_levels(self):
        result = create_codereview_result(
            output=json.dumps(
                [
                    {"file": "src/app.al", "line_start": 1, "body": "a", "severity": "warning"},
                    {"file": "src/app.al", "line_start": 2, "body": "b", "severity": "suggestion"},
                    {"file": "src/app.al", "line_start": 3, "body": "c", "severity": "error"},
                ]
            )
        )

        severities = [comment.severity for comment in result.generated_comments]
        assert severities == ["medium", "low", "high"]


class TestCodeReviewSummary:
    def test_summary_aggregates_precision_recall_and_f1(self):
        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity="warning"),
            ReviewComment(file="src/app.al", line_start=30, body="Fix auth check", severity="high"),
        ]

        result_1 = create_codereview_result(
            instance_id="a__1",
            output=json.dumps(
                [
                    {"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"},
                    {"file": "src/other.al", "line_start": 80, "body": "Issue B", "severity": "low"},
                ]
            ),
            expected_comments=expected_comments,
        )
        result_2 = create_codereview_result(
            instance_id="a__2",
            output="[]",
            expected_comments=expected_comments,
        )

        summary = CodeReviewResultSummary.from_results([result_1, result_2], run_id="run-1")

        assert summary.generated_comment_count == 2
        assert summary.expected_comment_count == 4
        assert summary.matched_comment_count == 1
        assert summary.incorrect_comment_count == 1
        assert summary.missed_comment_count == 3
        assert summary.precision == 0.5
        assert summary.recall == 0.25
        assert summary.f1 == 0.333


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
