import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.dataset import CodeReviewEntry
from bcbench.dataset.codereview import ReviewComment, Severity
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.codereview_judge import JUDGE_RESULT_FILE, LLMJudgeError, _parse_judge_results, judge_comment_matches
from bcbench.evaluate.review_parsing import parse_review_output
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.codereview import CodeReviewResult, CodeReviewResultSummary, match_comments
from bcbench.types import EvaluationCategory
from tests.conftest import create_codereview_entry, create_codereview_result, create_evaluation_context


class TestSeverity:
    def test_canonical_values_parse_directly(self):
        assert Severity.from_input("Critical") is Severity.CRITICAL
        assert Severity.from_input(" high ") is Severity.HIGH

    def test_aliases_map_to_canonical_severities(self):
        assert Severity.from_input("error") is Severity.HIGH
        assert Severity.from_input("warning") is Severity.MEDIUM
        assert Severity.from_input("suggestion") is Severity.LOW
        assert Severity.from_input("info") is Severity.LOW

    def test_unknown_severity_raises(self):
        with pytest.raises(ValueError, match="Unknown severity"):
            Severity.from_input("bogus")

    def test_levels_are_strictly_ordered(self):
        assert Severity.CRITICAL.level > Severity.HIGH.level > Severity.MEDIUM.level > Severity.LOW.level

    def test_review_comment_normalizes_severity_on_construction(self):
        comment = ReviewComment.model_validate({"file": "src/app.al", "line_start": 1, "body": "x", "severity": "warning"})
        assert comment.severity is Severity.MEDIUM

    def test_parser_skips_comment_with_unknown_severity_without_dropping_review(self):
        output = json.dumps(
            [
                {"file": "a.al", "line_start": 1, "body": "valid", "severity": "high"},
                {"file": "a.al", "line_start": 2, "body": "bad severity", "severity": "bogus"},
            ]
        )
        comments = parse_review_output(output)
        assert comments is not None
        assert [c.body for c in comments] == ["valid"]


class TestMatchComments:
    def test_finding_matches_nearest_expected_not_first_listed(self):
        expected = [
            ReviewComment(file="a.al", line_start=14, body="RecordRef in loop", severity=Severity.HIGH),
            ReviewComment(file="a.al", line_start=16, body="Commit in loop", severity=Severity.HIGH),
        ]
        generated = [ReviewComment(file="a.al", line_start=16, body="Commit() inside repeat", severity=Severity.HIGH)]

        pairs = match_comments(expected, generated, line_tolerance=2)

        assert len(pairs) == 1
        matched_expected, matched_generated = pairs[0]
        assert matched_expected.line_start == 16
        assert matched_generated.line_start == 16

    def test_maximizes_number_of_matches_within_tolerance(self):
        expected = [
            ReviewComment(file="a.al", line_start=10, body="issue A", severity=Severity.HIGH),
            ReviewComment(file="a.al", line_start=11, body="issue B", severity=Severity.HIGH),
        ]
        generated = [
            ReviewComment(file="a.al", line_start=10, body="near both", severity=Severity.HIGH),
            ReviewComment(file="a.al", line_start=12, body="near A only", severity=Severity.HIGH),
        ]

        pairs = match_comments(expected, generated, line_tolerance=2)

        assert len(pairs) == 2
        assert {matched_expected.line_start for matched_expected, _ in pairs} == {10, 11}

    def test_no_match_across_files(self):
        expected = [ReviewComment(file="a.al", line_start=10, body="x", severity=Severity.HIGH)]
        generated = [ReviewComment(file="b.al", line_start=10, body="x", severity=Severity.HIGH)]

        assert match_comments(expected, generated, line_tolerance=5) == []

    def test_no_match_beyond_tolerance(self):
        expected = [ReviewComment(file="a.al", line_start=10, body="x", severity=Severity.HIGH)]
        generated = [ReviewComment(file="a.al", line_start=20, body="x", severity=Severity.HIGH)]

        assert match_comments(expected, generated, line_tolerance=5) == []

    def test_empty_inputs_return_no_pairs(self):
        comment = ReviewComment(file="a.al", line_start=1, body="x", severity=Severity.HIGH)
        assert match_comments([], [comment], line_tolerance=5) == []
        assert match_comments([comment], [], line_tolerance=5) == []

    def test_none_tolerance_pairs_same_file_regardless_of_distance(self):
        expected = [ReviewComment(file="a.al", line_start=10, body="x", severity=Severity.HIGH)]
        generated = [ReviewComment(file="a.al", line_start=900, body="x", severity=Severity.HIGH)]

        pairs = match_comments(expected, generated, line_tolerance=None)

        assert len(pairs) == 1

    def test_none_tolerance_still_never_pairs_across_files(self):
        expected = [ReviewComment(file="a.al", line_start=10, body="x", severity=Severity.HIGH)]
        generated = [ReviewComment(file="b.al", line_start=10, body="x", severity=Severity.HIGH)]

        assert match_comments(expected, generated, line_tolerance=None) == []

    def test_none_tolerance_uses_distance_as_tiebreak(self):
        expected = [ReviewComment(file="a.al", line_start=10, body="x", severity=Severity.HIGH)]
        generated = [
            ReviewComment(file="a.al", line_start=500, body="far", severity=Severity.HIGH),
            ReviewComment(file="a.al", line_start=12, body="near", severity=Severity.HIGH),
        ]

        pairs = match_comments(expected, generated, line_tolerance=None)

        assert len(pairs) == 1
        _, matched_generated = pairs[0]
        assert matched_generated.line_start == 12


class TestCodeReviewEntry:
    def test_get_task_returns_patch(self):
        entry = create_codereview_entry(patch="diff --git a/test.al b/test.al\n+new line")
        assert entry.get_task() == "diff --git a/test.al b/test.al\n+new line"

    def test_get_expected_output_formats_comments(self):
        comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix this", severity=Severity.MEDIUM),
            ReviewComment(file="src/app.al", line_start=20, body="Consider that", severity=Severity.LOW),
        ]
        entry = create_codereview_entry(expected_comments=comments)
        output = entry.get_expected_output()
        assert "[medium] src/app.al:10: Fix this" in output
        assert "[low] src/app.al:20: Consider that" in output

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
            instance_id="test__rt-1",
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
            "line_tolerance": 5,
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

    def test_parses_single_finding_object_output(self):
        output = json.dumps(
            {
                "filePath": "src/app.al",
                "lineNumber": 42,
                "severity": "Medium",
                "issue": "Potential issue in single-object response",
                "recommendation": "Fix it",
                "suggestedCode": "",
            }
        )

        result = create_codereview_result(output=output)

        assert result.valid_review_output is True
        assert len(result.generated_comments) == 1
        assert result.generated_comments[0].file == "src/app.al"
        assert result.generated_comments[0].line_start == 42

    def test_metrics_match_expected_comments_with_tolerance(self):
        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
            ReviewComment(file="src/app.al", line_start=40, body="Validate input", severity=Severity.HIGH),
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

    def test_display_row_splits_comment_counts(self):
        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
            ReviewComment(file="src/app.al", line_start=40, body="Validate input", severity=Severity.HIGH),
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

        assert result.display_row == {
            "Generated": "2",
            "Matched": "1",
            "Expected": "2",
            "Precision": "0.50",
            "Recall": "0.50",
            "F1": "0.50",
        }

    def test_result_leaves_generated_comment_domain_unset_when_absent(self):
        result = create_codereview_result(
            output='[{"file": "src/app.al", "line_start": 5, "body": "Issue", "severity": "medium"}]',
            expected_comments=[],
            domain="performance",
        )

        assert len(result.generated_comments) == 1
        assert result.generated_comments[0].domain is None

    def test_result_keeps_generated_comments_with_mismatched_domain(self):
        result = create_codereview_result(
            output='[{"file": "src/app.al", "line_start": 5, "domain": "security", "body": "Issue", "severity": "medium"}]',
            expected_comments=[],
            domain="performance",
        )

        assert len(result.generated_comments) == 1
        assert result.generated_comments[0].domain == "security"

    def test_result_preserves_explicit_generated_comment_domain_when_matching(self):
        result = create_codereview_result(
            output='[{"file": "src/app.al", "line_start": 5, "domain": "performance", "body": "Issue", "severity": "medium"}]',
            expected_comments=[],
            domain="performance",
        )

        assert len(result.generated_comments) == 1
        assert result.generated_comments[0].domain == "performance"


class TestCodeReviewSummary:
    def test_summary_aggregates_precision_recall_and_f1(self):
        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
            ReviewComment(file="src/app.al", line_start=30, body="Fix auth check", severity=Severity.HIGH),
        ]

        result_1 = create_codereview_result(
            instance_id="test__a-1",
            output=json.dumps(
                [
                    {"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"},
                    {"file": "src/other.al", "line_start": 80, "body": "Issue B", "severity": "low"},
                ]
            ),
            expected_comments=expected_comments,
        )
        result_2 = create_codereview_result(
            instance_id="test__a-2",
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

    def test_macro_precision_excludes_silent_tasks(self):
        expected_comments = [ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM)]

        commenting = create_codereview_result(
            instance_id="test__macro-1",
            output=json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}]),
            expected_comments=expected_comments,
        )
        silent = create_codereview_result(
            instance_id="test__macro-2",
            output="[]",
            expected_comments=expected_comments,
        )

        summary = CodeReviewResultSummary.from_results([commenting, silent], run_id="run-1")

        # Only the task where the agent actually commented (precision 1.0) feeds macro precision;
        # the silent task's convention precision of 1.0 must not be averaged in.
        assert summary.macro_precision == 1.0
        # Recall still spans both tasks: 1.0 for the hit, 0.0 for the silent miss.
        assert summary.macro_recall == 0.5

    def test_macro_precision_zero_when_all_tasks_silent(self):
        expected_comments = [ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM)]
        silent = create_codereview_result(instance_id="test__silent-1", output="[]", expected_comments=expected_comments)

        summary = CodeReviewResultSummary.from_results([silent], run_id="run-1")

        assert summary.macro_precision == 0.0

    def test_render_github_metrics_markdown_has_grouped_sections(self):
        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
        ]
        result = create_codereview_result(
            instance_id="test__render-1",
            output=json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}]),
            expected_comments=expected_comments,
        )

        summary = CodeReviewResultSummary.from_results([result], run_id="run-1")
        markdown = summary.render_github_metrics_markdown()

        # Section headers replace the old flat bullet list.
        assert "## Comment counts" in markdown
        assert "## Micro metrics (volume-weighted across all comments)" in markdown
        assert "## Macro metrics (averaged per task)" in markdown
        assert "## Quality" in markdown
        assert "## Result Summary" not in markdown

        # Percent units applied to rate-style metrics.
        assert "100.0%" in markdown

        # Beta renders as the Greek symbol, not the LaTeX escape sequence.
        assert "β" in markdown
        assert "\\beta" not in markdown

        # Collapsible explanations are present.
        assert "<details>" in markdown
        assert "How to read these metrics" in markdown
        assert "LLM judge" in markdown
        assert "F_β = (1 + β²)" in markdown

    def test_render_console_metrics_uses_grouped_rich_tables(self):
        from io import StringIO

        from rich.console import Console

        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
        ]
        result = create_codereview_result(
            instance_id="test__render-1",
            output=json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}]),
            expected_comments=expected_comments,
        )

        summary = CodeReviewResultSummary.from_results([result], run_id="run-1")
        buffer = StringIO()
        # Force a wide terminal so Rich does not truncate column headers in the captured output.
        console = Console(file=buffer, force_terminal=False, width=200)
        console.print(summary.render_console_metrics())
        output = buffer.getvalue()

        # Grouped section titles appear instead of the old flat key/value bullets.
        assert "Comment counts" in output
        assert "Micro metrics" in output
        assert "Macro metrics" in output
        assert "Quality" in output

        # Percent units on rate-style metrics; Greek beta, not LaTeX.
        assert "100.0%" in output
        assert "β" in output
        assert "\\beta" not in output

        # Explanations panel rendered.
        assert "How to read these metrics" in output
        assert "LLM judge" in output


class TestCodeReviewLeaderboardAggregate:
    def _make_summary(self, expected_comments, output: str, run_id: str) -> CodeReviewResultSummary:
        result = create_codereview_result(
            instance_id="test__a-1",
            output=output,
            expected_comments=expected_comments,
        )
        return CodeReviewResultSummary.from_results([result], run_id=run_id)

    def test_aggregate_uses_f1_as_average_and_has_no_pass_hat_5(self):
        from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, LeaderboardAggregate

        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
        ]
        output = json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}])

        run = self._make_summary(expected_comments, output, run_id="run-1")

        agg = LeaderboardAggregate.from_runs([run])

        assert isinstance(agg, CodeReviewLeaderboardAggregate)
        assert agg.category == EvaluationCategory.CODE_REVIEW
        assert agg.num_runs == 1
        assert agg.f1 == run.f1
        assert not hasattr(agg, "pass_hat_5")

    def test_macro_f1_ci_is_bootstrapped_over_tasks_for_single_run(self):
        from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, LeaderboardAggregate

        expected = [ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM)]
        hit = json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}])

        results = [
            create_codereview_result(instance_id="test__t-1", output=hit, expected_comments=expected),
            create_codereview_result(instance_id="test__t-2", output="[]", expected_comments=expected),
            create_codereview_result(instance_id="test__t-3", output=hit, expected_comments=expected),
            create_codereview_result(instance_id="test__t-4", output="[]", expected_comments=expected),
        ]
        run = CodeReviewResultSummary.from_results(results, run_id="run-1")

        # Per-task F1 is retained so the CI can be bootstrapped over tasks.
        assert run.per_task_f1 == [1.0, 0.0, 1.0, 0.0]

        agg = LeaderboardAggregate.from_runs([run])

        # A single run with varying per-task F1 still yields a real (task-level) CI.
        assert isinstance(agg, CodeReviewLeaderboardAggregate)
        assert agg.macro_f1_ci_low is not None
        assert agg.macro_f1_ci_high is not None
        assert agg.macro_f1_ci_low <= agg.macro_f1 <= agg.macro_f1_ci_high

    def test_aggregate_serialization_excludes_pass_hat_5(self):
        from bcbench.results.leaderboard import Leaderboard, LeaderboardAggregate

        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
        ]
        output = json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}])

        run = self._make_summary(expected_comments, output, run_id="run-1")
        agg = LeaderboardAggregate.from_runs([run])

        leaderboard = Leaderboard(runs=[run], aggregate=[agg])
        data = leaderboard.to_dict()

        assert "pass_hat_5" not in data["aggregate"][0]
        assert data["aggregate"][0]["f1"] == run.f1

    def test_round_trip_preserves_codereview_subclasses(self):
        from bcbench.results.codereview import CodeReviewResultSummary as CRSummary
        from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, Leaderboard, LeaderboardAggregate

        expected_comments = [
            ReviewComment(file="src/app.al", line_start=10, body="Fix null check", severity=Severity.MEDIUM),
        ]
        output = json.dumps([{"file": "src/app.al", "line_start": 10, "body": "Issue A", "severity": "warning"}])

        run = self._make_summary(expected_comments, output, run_id="run-1")
        agg = LeaderboardAggregate.from_runs([run])
        leaderboard = Leaderboard(runs=[run], aggregate=[agg])

        restored = Leaderboard.model_validate(leaderboard.to_dict())

        assert isinstance(restored.runs[0], CRSummary)
        assert isinstance(restored.aggregate[0], CodeReviewLeaderboardAggregate)


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

    def test_setup_workspace_applies_entry_patch(self, tmp_path):
        entry = create_codereview_entry(patch="diff --git a/a.al b/a.al\n+new line\n")
        pipeline = CodeReviewPipeline()

        with (
            patch("bcbench.evaluate.codereview.setup_repo_prebuild") as mock_setup,
            patch("bcbench.evaluate.codereview.apply_patch") as mock_apply,
        ):
            pipeline.setup_workspace(entry, Path(tmp_path))

        mock_setup.assert_called_once()
        mock_apply.assert_called_once()

    def test_setup_workspace_marks_new_files_as_intent_to_add(self, tmp_path):
        entry = create_codereview_entry(
            patch=(
                "diff --git a/src/NewObject.Codeunit.al b/src/NewObject.Codeunit.al\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                "+++ b/src/NewObject.Codeunit.al\n"
                "@@ -0,0 +1,3 @@\n"
                "+codeunit 50100 NewObject\n"
                "+{\n"
                "+}\n"
            )
        )
        pipeline = CodeReviewPipeline()
        subprocess.run(["git", "init"], cwd=tmp_path, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "init"],
            cwd=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )

        with patch("bcbench.evaluate.codereview.setup_repo_prebuild") as mock_setup:
            pipeline.setup_workspace(entry, Path(tmp_path))

        mock_setup.assert_called_once()
        new_file = Path(tmp_path) / "src" / "NewObject.Codeunit.al"
        assert new_file.exists()
        assert "codeunit 50100 NewObject" in new_file.read_text(encoding="utf-8")
        diff = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "src/NewObject.Codeunit.al" in diff

    def test_evaluate_raises_when_no_review_generated(self, tmp_path):
        entry = create_codereview_entry()
        context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.CODE_REVIEW)
        pipeline = CodeReviewPipeline()

        with pytest.raises(RuntimeError, match="No review generated"):
            pipeline.evaluate(context)


class TestJudge:
    @staticmethod
    def _pair(line: int) -> tuple[ReviewComment, ReviewComment]:
        expected = ReviewComment(file="src/app.al", line_start=line, body="expected", severity=Severity.MEDIUM)
        generated = ReviewComment(file="src/app.al", line_start=line, body="generated", severity=Severity.MEDIUM)
        return expected, generated

    def test_parse_raises_when_result_file_missing(self, tmp_path):
        with pytest.raises(LLMJudgeError, match="no result file"):
            _parse_judge_results(tmp_path / JUDGE_RESULT_FILE, num_pairs=1)

    def test_parse_raises_on_invalid_json(self, tmp_path):
        result_path = tmp_path / JUDGE_RESULT_FILE
        result_path.write_text("not json", encoding="utf-8")

        with pytest.raises(LLMJudgeError, match="not valid JSON"):
            _parse_judge_results(result_path, num_pairs=1)

    def test_parse_raises_when_not_a_list(self, tmp_path):
        result_path = tmp_path / JUDGE_RESULT_FILE
        result_path.write_text('{"pair": 1, "match": true}', encoding="utf-8")

        with pytest.raises(LLMJudgeError, match="must be a JSON list"):
            _parse_judge_results(result_path, num_pairs=1)

    def test_parse_missing_pair_counts_as_not_confirmed(self, tmp_path):
        result_path = tmp_path / JUDGE_RESULT_FILE
        result_path.write_text('[{"pair": 1, "match": true}]', encoding="utf-8")

        assert _parse_judge_results(result_path, num_pairs=2) == [True, False]

    def test_parse_falls_back_to_stdout_when_file_missing(self, tmp_path):
        result_path = tmp_path / JUDGE_RESULT_FILE

        assert _parse_judge_results(result_path, num_pairs=1, stdout='```json\n[{"pair": 1, "match": true}]\n```') == [True]

    def test_empty_pairs_skips_judge(self):
        assert judge_comment_matches([], work_dir=Path()) == []

    def test_raises_when_copilot_not_found(self, tmp_path):
        with patch("bcbench.evaluate.codereview_judge._find_copilot", return_value=None), pytest.raises(LLMJudgeError, match="Copilot CLI not found"):
            judge_comment_matches([self._pair(10)], work_dir=tmp_path)

    def test_raises_when_subprocess_fails(self, tmp_path):
        with (
            patch("bcbench.evaluate.codereview_judge._find_copilot", return_value="copilot"),
            patch(
                "bcbench.evaluate.codereview_judge.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "copilot"),
            ),
            pytest.raises(LLMJudgeError, match="Judge subprocess failed"),
        ):
            judge_comment_matches([self._pair(10)], work_dir=tmp_path)

    def test_subprocess_failure_surfaces_copilot_output(self, tmp_path):
        error = subprocess.CalledProcessError(1, "copilot", output="partial stdout", stderr="model gpt-5.3-codex is not available")
        with (
            patch("bcbench.evaluate.codereview_judge._find_copilot", return_value="copilot"),
            patch("bcbench.evaluate.codereview_judge.subprocess.run", side_effect=error),
            pytest.raises(LLMJudgeError, match="model gpt-5\\.3-codex is not available"),
        ):
            judge_comment_matches([self._pair(10)], work_dir=tmp_path)

    def test_filters_to_confirmed_pairs(self, tmp_path):
        pairs = [self._pair(10), self._pair(20)]

        def fake_run(*args, **kwargs):
            (tmp_path / JUDGE_RESULT_FILE).write_text('[{"pair": 1, "match": true}, {"pair": 2, "match": false}]', encoding="utf-8")
            return subprocess.CompletedProcess(args, 0)

        with (
            patch("bcbench.evaluate.codereview_judge._find_copilot", return_value="copilot"),
            patch("bcbench.evaluate.codereview_judge.subprocess.run", side_effect=fake_run),
        ):
            result = judge_comment_matches(pairs, work_dir=tmp_path)

        assert result == [pairs[0]]

    def test_filters_using_stdout_when_file_not_written(self, tmp_path):
        pairs = [self._pair(10), self._pair(20)]

        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout='[{"pair": 1, "match": false}, {"pair": 2, "match": true}]')

        with (
            patch("bcbench.evaluate.codereview_judge._find_copilot", return_value="copilot"),
            patch("bcbench.evaluate.codereview_judge.subprocess.run", side_effect=fake_run),
        ):
            result = judge_comment_matches(pairs, work_dir=tmp_path)

        assert result == [pairs[1]]
