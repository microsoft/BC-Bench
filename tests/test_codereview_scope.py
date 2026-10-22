import json
from unittest.mock import patch

import pytest
import yaml
from rich.console import Console

from bcbench.config import get_config
from bcbench.dataset.codereview import ReviewComment, Severity
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.codereview import CodeReviewResult, CodeReviewResultSummary
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, Leaderboard
from bcbench.types import EvaluationCategory
from tests.conftest import create_codereview_entry, create_evaluation_context


def _comment(body, severity=None, line=1):
    return ReviewComment(file="src/app.al", line_start=line, body=body, severity=severity)


def _evaluate(tmp_path, expected, generated, ignored=None, all_edges=False):
    entry = create_codereview_entry(expected_comments=expected, ignored_comments=ignored or [])
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.CODE_REVIEW)
    context.repo_path.mkdir()
    (context.repo_path / "review.json").write_text(json.dumps([comment.model_dump(mode="json") for comment in generated]), encoding="utf-8")
    pipeline = CodeReviewPipeline()
    with patch("bcbench.evaluate.codereview_judge.judge_verdicts", side_effect=lambda pairs, *_args, **_kwargs: [all_edges or gold.body == output.body for gold, output in pairs]) as judge:
        pipeline.evaluate(context)
    judge.assert_called_once()
    assert len(judge.call_args.args[0]) == (len(expected) + len(ignored or [])) * len(generated)
    result = BaseEvaluationResult.from_json(json.loads(next(context.result_dir.glob("*.jsonl")).read_text(encoding="utf-8")))
    assert isinstance(result, CodeReviewResult)
    return result


def test_scope_matches_the_frozen_runner_floor():
    config = yaml.safe_load((get_config().paths.agent_share_dir / "config.yaml").read_text(encoding="utf-8"))
    assert CodeReviewPipeline.minimum_severity == Severity.from_input(config["pr_review"]["min_severity"]) == Severity.MEDIUM


@pytest.mark.parametrize("severity", [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, None])
def test_scope_keeps_in_scope_and_unknown_gold_even_if_output_calls_it_low(tmp_path, severity):
    result = _evaluate(tmp_path, [_comment("issue", severity)], [_comment("issue", Severity.LOW)])
    assert len(result.expected_comments) == result.matched_comment_count == 1
    assert result.out_of_scope_comments == []
    assert result.unscoped_result is not None
    assert result.unscoped_result.matched_comment_count == 1
    assert result.unscoped_result.unscoped_result is None
    assert result.minimum_severity == Severity.MEDIUM


@pytest.mark.parametrize("severity", [Severity.CRITICAL, Severity.LOW, None])
def test_low_gold_matches_are_neutral_regardless_of_output_severity(tmp_path, severity):
    result = _evaluate(tmp_path, [_comment("low issue", Severity.LOW)], [_comment("low issue", severity), _comment("unrelated", Severity.LOW)])
    assert result.expected_comments == []
    assert len(result.generated_comments) == 2
    assert result.matched_comment_count == 0
    assert result.ignored_matched_comment_count == result.out_of_scope_matched_comment_count == 1
    assert result.incorrect_comment_count == 1
    assert result.precision == 0
    assert result.unscoped_result is not None
    assert result.unscoped_result.matched_comment_count == 1
    assert result.unscoped_result.precision == 0.5
    assert result.unscoped_result.ignored_comments == []


def test_in_scope_credit_wins_over_closer_neutral_gold(tmp_path):
    result = _evaluate(tmp_path, [_comment("low", Severity.LOW, 1), _comment("high", Severity.HIGH, 100)], [_comment("consolidated", Severity.MEDIUM, 1)], all_edges=True)
    assert result.matched_comment_count == 1
    assert result.out_of_scope_matched_comment_count == 0
    assert result.ignored_matched_comment_count == 0
    assert result.expected_comments[0].body == "high"
    assert result.unscoped_result is not None
    assert len(result.unscoped_result.expected_comments) == 2
    assert result.unscoped_result.matched_comment_count == 1


def test_low_neutralization_stays_one_to_one_and_preserves_declared_ignored(tmp_path):
    result = _evaluate(
        tmp_path,
        [_comment("low", Severity.LOW)],
        [_comment("low"), _comment("low"), _comment("optional"), _comment("unexpected")],
        ignored=[_comment("optional", Severity.MEDIUM)],
    )
    assert result.out_of_scope_matched_comment_count == 1
    assert result.ignored_matched_comment_count == 2
    assert result.incorrect_comment_count == 2
    assert result.unscoped_result is not None
    assert result.unscoped_result.ignored_matched_comment_count == 1
    assert result.unscoped_result.matched_comment_count == 1


def test_all_23_low_gold_are_scoped_not_only_the_13_misses(tmp_path):
    expected = [_comment(f"medium-{index}", Severity.MEDIUM) for index in range(179)] + [_comment(f"low-{index}", Severity.LOW) for index in range(23)]
    generated = expected[:95] + expected[179:189] + [_comment(f"unmatched-{index}", Severity.LOW) for index in range(322)]
    result = _evaluate(tmp_path, expected, generated)
    assert result.unscoped_result is not None
    original = result.unscoped_result
    assert (original.matched_comment_count, len(original.expected_comments), original.incorrect_comment_count) == (105, 202, 322)
    assert original.recall == pytest.approx(105 / 202)
    assert original.precision == pytest.approx(105 / 427)
    assert (result.matched_comment_count, len(result.expected_comments), result.incorrect_comment_count) == (95, 179, 322)
    assert len(result.out_of_scope_comments) == 23
    assert result.out_of_scope_matched_comment_count == 10
    assert result.recall == pytest.approx(95 / 179)
    assert result.precision == pytest.approx(95 / 417)


@pytest.mark.parametrize("include_medium", [False, True])
def test_invalid_output_preserves_both_gold_populations_without_neutral_credit(tmp_path, include_medium):
    expected = [_comment("low", Severity.LOW)] + ([_comment("medium", Severity.MEDIUM)] if include_medium else [])
    entry = create_codereview_entry(expected_comments=expected)
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.CODE_REVIEW)
    context.repo_path.mkdir()
    (context.repo_path / "review.json").write_text("invalid", encoding="utf-8")
    pipeline = CodeReviewPipeline()
    with patch("bcbench.evaluate.codereview_judge.judge_verdicts") as judge, patch.object(pipeline, "save_result") as save:
        pipeline.evaluate(context)
    judge.assert_not_called()
    result = save.call_args.args[1]
    assert not result.valid_review_output
    assert result.f1 == 0
    assert len(result.expected_comments) == int(include_medium)
    assert len(result.out_of_scope_comments) == 1
    assert result.out_of_scope_matched_comment_count == 0
    assert len(result.unscoped_result.expected_comments) == 1 + int(include_medium)
    assert result.unscoped_result.f1 == 0
    summary = CodeReviewResultSummary.from_results([result], "invalid")
    assert summary.precision == summary.recall == summary.f1 == 0
    assert summary.macro_precision == summary.macro_recall == summary.macro_f1 == 0


def test_dual_scope_survives_summary_export_and_leaderboard_roundtrip(tmp_path):
    result = _evaluate(tmp_path, [_comment("low", Severity.LOW), _comment("high", Severity.HIGH)], [_comment("low")])
    summary = CodeReviewResultSummary.from_results([result], "test")
    assert summary.minimum_severity == Severity.MEDIUM
    assert summary.expected_comment_count == 1
    assert summary.out_of_scope_comment_count == 1
    assert summary.out_of_scope_matched_comment_count == 1
    assert summary.unscoped_summary is not None
    assert summary.unscoped_summary.expected_comment_count == 2
    assert summary.unscoped_summary.recall == 0.5
    assert summary.unscoped_summary.unscoped_summary is None
    markdown = summary.render_github_metrics_markdown()
    assert "Unscoped (all gold)" in markdown
    assert "Scoring scope: gold >= medium" in markdown
    console = Console(record=True, width=200)
    console.print(summary.render_console_metrics())
    assert "original all-gold view" in console.export_text()
    assert result.export_metadata["scoring_scope"] == "gold>=medium"
    assert result.category_metrics["unscoped_recall"] == 0.5
    assert result.category_metrics["out_of_scope_matched_comment_count"] == 1
    assert "Unscoped P/R/F1" in result.display_row
    aggregate = CodeReviewLeaderboardAggregate.from_runs([summary])
    restored = Leaderboard.model_validate(Leaderboard(runs=[summary], aggregate=[aggregate]).to_dict())
    restored_aggregate = restored.aggregate[0]
    assert isinstance(restored_aggregate, CodeReviewLeaderboardAggregate)
    assert restored_aggregate.minimum_severity == Severity.MEDIUM
    assert restored_aggregate.unscoped_aggregate is not None
    assert restored_aggregate.unscoped_aggregate.recall == 0.5


def test_mixed_scope_aggregation_fails_loudly(tmp_path):
    result = _evaluate(tmp_path, [_comment("low", Severity.LOW)], [])
    assert result.unscoped_result is not None
    with pytest.raises(ValueError, match="different severity scopes"):
        CodeReviewResultSummary.from_results([result, result.unscoped_result], "mixed")
    scoped = CodeReviewResultSummary.from_results([result], "scoped")
    original = CodeReviewResultSummary.from_results([result.unscoped_result], "original")
    with pytest.raises(ValueError, match="different severity scopes"):
        CodeReviewLeaderboardAggregate.from_runs([scoped, original])
