import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from bcbench.dataset.codereview import ReviewComment, ReviewCommentKind, Severity
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.codereview_judge import JUDGE_PROTOCOL, _build_judge_prompt, _parse_judge_results, judge_verdicts
from bcbench.exceptions import LLMJudgeError
from bcbench.results.base import BaseEvaluationResult
from bcbench.results.codereview import CodeReviewResult, CodeReviewResultSummary, assign_comment_matches, candidate_comment_pairs
from bcbench.results.leaderboard import CodeReviewLeaderboardAggregate, Leaderboard
from bcbench.types import CodeReviewScoringMode, EvaluationCategory
from tests.conftest import create_codereview_entry, create_evaluation_context


def comment(body, line=10, severity=Severity.MEDIUM, file="src/app.al", kind=ReviewCommentKind.REVIEW_FINDING):
    return ReviewComment(file=file, line_start=line, line_end=line + 2, body=body, severity=severity, kind=kind)


def evaluate(tmp_path, expected, generated, verdicts, ignored=None, source=""):
    entry = create_codereview_entry(expected_comments=expected, ignored_comments=ignored or [], **({"patch": source} if source else {}))
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.CODE_REVIEW)
    context.repo_path.mkdir()
    (context.repo_path / "review.json").write_text(json.dumps([c.model_dump(mode="json") for c in generated]), encoding="utf-8")
    response = json.dumps([{"pair": i + 1, "match": match, "reasoning": f"Fixture verdict {i + 1}"} for i, match in enumerate(verdicts)])
    with patch("bcbench.evaluate.codereview_judge.invoke_copilot", return_value=(None, response)) as invoke:
        CodeReviewPipeline().evaluate(context)
    saved = next(context.result_dir.glob("*.jsonl")).read_text(encoding="utf-8")
    result = CodeReviewResult.model_validate_json(saved)
    assert result.judge_protocol == JUDGE_PROTOCOL
    assert result.scoring_mode == CodeReviewScoringMode.ANY_MATCH
    assert result.judge_evidence is not None
    assert len(result.judge_evidence.edges) == len(verdicts)
    assert result.judge_evidence.source_patch_sha256 == hashlib.sha256(entry.patch.encode()).hexdigest()
    assert invoke.call_count == int(bool(verdicts))
    if verdicts:
        assert json.dumps(entry.patch) in invoke.call_args.kwargs["prompt"]
        assert invoke.call_args.kwargs["model"] == "gpt-5.3-codex"
    return result


def test_bundled_one_comment_covers_three_gold_without_three_precision_tp(tmp_path):
    result = evaluate(tmp_path, [comment("A"), comment("B", 50), comment("C", 100)], [comment("A, B and C", 2)], [True] * 3)
    assert (result.matched_comment_count, result.covered_gold_count, result.missed_comment_count) == (1, 3, 0)
    assert result.precision == result.recall == 1
    assert len(result.positive_matches) == 3
    legacy = result.legacy_result
    assert legacy is not None
    assert legacy.scoring_mode == CodeReviewScoringMode.LEGACY
    assert (legacy.matched_comment_count, legacy.covered_gold_count, legacy.missed_comment_count) == (1, 1, 2)
    assert legacy.recall == pytest.approx(1 / 3)
    assert legacy.judge_protocol == result.judge_protocol
    assert legacy.unscoped_result is not None
    assert result.category_metrics["legacy_covered_gold_count"] == 1
    assert result.export_metadata["scoring_mode"] == "any-match"


def test_two_duplicate_comments_get_two_precision_tp_but_one_gold(tmp_path):
    result = evaluate(tmp_path, [comment("A")], [comment("A"), comment("A")], [True, True])
    assert (result.matched_comment_count, result.covered_gold_count, result.incorrect_comment_count) == (2, 1, 0)
    assert result.redundant_matched_comment_count == 1
    assert result.precision == result.recall == 1
    assert result.legacy_result.incorrect_comment_count == 1
    assert result.legacy_result.precision == 0.5


def test_positive_part_wins_over_wrong_extra_claim_and_all_neutral_buckets(tmp_path):
    mechanical = comment("syntax", kind=ReviewCommentKind.COMPILER_DIAGNOSTIC)
    result = evaluate(
        tmp_path,
        [comment("required"), mechanical, comment("Low", severity=Severity.LOW)],
        [comment("required, optional, Low, syntax, and an incorrect extra allegation")],
        [True] * 4,
        ignored=[comment("optional")],
    )
    assert result.matched_comment_count == result.covered_gold_count == 1
    assert result.ignored_matched_comment_count == result.mechanical_matched_comment_count == result.out_of_scope_matched_comment_count == 0
    assert result.unscoped_result.covered_gold_count == 2
    assert result.unscoped_result.matched_comment_count == 1


def test_all_neutral_only_duplicates_excluded_and_unmatched_stays_fp(tmp_path):
    result = evaluate(
        tmp_path,
        [comment("Low", severity=Severity.LOW)],
        [comment("Low"), comment("Low"), comment("optional"), comment("unmatched")],
        [True, True, False, False, False, False, True, False],
        ignored=[comment("optional")],
    )
    assert (result.matched_comment_count, result.covered_gold_count, result.ignored_matched_comment_count, result.incorrect_comment_count) == (0, 0, 3, 1)
    assert result.out_of_scope_matched_comment_count == 2
    assert result.unscoped_result.matched_comment_count == 2
    assert result.unscoped_result.covered_gold_count == 1
    assert result.legacy_result.ignored_matched_comment_count == 2
    assert result.legacy_result.incorrect_comment_count == 2


def test_micro_summary_uses_covered_gold_and_preserves_four_mode_scope_views(tmp_path):
    result = evaluate(tmp_path, [comment("A"), comment("B"), comment("C")], [comment("bundle")], [True] * 3)
    summary = CodeReviewResultSummary.from_results([result], "test")
    assert summary.matched_comment_count == 1
    assert summary.covered_gold_count == 3
    assert summary.recall == summary.precision == 1
    assert summary.legacy_summary is not None
    assert summary.legacy_summary.unscoped_summary is not None
    assert summary.unscoped_summary is not None
    assert summary.legacy_summary.recall == 0.333
    assert summary.legacy_summary.unscoped_summary.recall == 0.333
    assert summary.unscoped_summary.covered_gold_count == 3
    assert "same new judge edges, not historical scores" in summary.render_github_metrics_markdown()
    assert "Covered gold" in summary.render_github_metrics_markdown()
    aggregate = CodeReviewLeaderboardAggregate.from_runs([summary])
    restored = Leaderboard.model_validate(Leaderboard(runs=[summary], aggregate=[aggregate]).to_dict())
    restored_aggregate = restored.aggregate[0]
    assert isinstance(restored_aggregate, CodeReviewLeaderboardAggregate)
    assert restored_aggregate.legacy_aggregate is not None
    assert restored_aggregate.scoring_mode == CodeReviewScoringMode.ANY_MATCH
    assert restored_aggregate.legacy_aggregate.recall == 0.333
    assert summary.combination_key() != summary.legacy_summary.combination_key()
    with pytest.raises(ValueError, match="different scoring modes"):
        CodeReviewResultSummary.from_results([result, result.legacy_result], "mixed")
    with pytest.raises(ValueError, match="different combinations"):
        CodeReviewLeaderboardAggregate.from_runs([summary, summary.legacy_summary])


def test_old_serialized_result_loads_as_legacy_without_relabeling(tmp_path):
    result = evaluate(tmp_path, [comment("A")], [comment("A")], [True]).legacy_result
    raw = result.model_dump(mode="json", exclude={"scoring_mode", "judge_protocol", "covered_gold_count", "severity_pair_count", "positive_matches", "neutral_matches"})
    restored = BaseEvaluationResult.from_json(raw)
    assert isinstance(restored, CodeReviewResult)
    assert restored.scoring_mode == CodeReviewScoringMode.LEGACY
    assert restored.judge_protocol == "same-issue-v1"
    assert restored.covered_gold_count == restored.matched_comment_count == 1
    assert restored.recall == result.recall


def test_any_match_serialization_rejects_corrupt_counts_and_missing_edges(tmp_path):
    result = evaluate(tmp_path, [comment("A"), comment("B")], [comment("bundle")], [True, True])
    raw = result.model_dump(mode="json")
    raw["covered_gold_count"] = 1
    with pytest.raises(ValidationError, match="Stored counts"):
        CodeReviewResult.model_validate(raw)
    raw = result.model_dump(mode="json")
    raw["judge_evidence"]["edges"].pop()
    with pytest.raises(ValidationError, match="every eligible"):
        CodeReviewResult.model_validate(raw)


@pytest.mark.parametrize(
    "values",
    [
        [{"pair": 1, "match": "false"}],
        [{"pair": True, "match": True}],
        [{"pair": 1, "match": True}, {"pair": 1, "match": False}],
        [{"pair": 2, "match": True}],
        [],
    ],
)
def test_invalid_or_incomplete_judge_edges_cannot_be_scored(tmp_path, values):
    with pytest.raises(LLMJudgeError):
        _parse_judge_results(tmp_path / "absent.json", 1, json.dumps(values))


def test_judge_ignores_stale_result_and_does_not_collapse_source_lines(tmp_path):
    from bcbench.config import get_config

    path = tmp_path / get_config().judge.result_file
    path.write_text('[{"pair":1,"match":true}]', encoding="utf-8")
    source = "@@ -0,0 +1,2 @@\n+procedure BuildVendorReport()\n+begin\n"
    with patch("bcbench.evaluate.codereview_judge.invoke_copilot", return_value=(None, '[{"pair":1,"match":false}]')) as invoke:
        assert judge_verdicts([(comment("vendor"), comment("CSV"))], tmp_path, source_context=source) == [False]
    assert json.dumps(source) in invoke.call_args.kwargs["prompt"]
    assert not path.exists()


def test_specific_site_prompt_and_complete_edges_for_actual_performance023(tmp_path):
    rows = [json.loads(line) for line in Path("dataset/codereview.jsonl").read_text(encoding="utf-8").splitlines()]
    entry = next(row for row in rows if row["instance_id"] == "synthetic__performance-023")
    gold = [ReviewComment.model_validate(value) for value in entry["expected_comments"][:2]]
    assert len(gold) == 2
    assert "BuildCsvExport" in entry["patch"]
    assert "BuildVendorReport" in entry["patch"]
    # Deliberately displaced anchors: identity comes from the specific site, not proximity.
    csv_only = comment("BuildCsvExport repeatedly concatenates CsvText inside its loop; use TextBuilder.", line=500, file=gold[0].file)
    both = comment("Both BuildCsvExport's CsvText loop and BuildVendorReport's ReportText loop repeatedly concatenate text; use TextBuilder in each.", line=1, file=gold[0].file)
    result = evaluate(tmp_path, gold, [csv_only, both], [True, True, False, True], source=entry["patch"])
    assert result.covered_gold_count == 2
    edges = result.judge_evidence.edges
    assert [(edge.gold_index, edge.generated_index, edge.match) for edge in edges] == [(0, 0, True), (0, 1, True), (1, 0, False), (1, 1, True)]
    prompt = _build_judge_prompt(candidate_comment_pairs(gold, [csv_only, both]), "verdict.json", entry["patch"])
    assert "500-502" in prompt
    assert "no fixed line-distance cutoff" in prompt
    assert "BuildCsvExport must NOT match" in prompt
    assert "Do not impose one-to-one assignment" in prompt
    assert json.dumps(entry["patch"]) in prompt
    # This verifies the real prompt/edge plumbing, not live LLM semantic accuracy.


def test_path_normalization_is_unchanged_and_does_not_use_nearest_candidate():
    gold = [comment("same", line=10).model_copy(update={"file": "./src/app.al"}), comment("other site", line=900)]
    generated = [comment("same", line=500).model_copy(update={"file": "src\\app.al"}), comment("same", file="other.al")]
    pairs = candidate_comment_pairs(gold, generated)
    assert len(pairs) == 2
    assert all(generated_comment is generated[0] for _, generated_comment in pairs)
    matched, _ = assign_comment_matches(pairs, [], scoring_mode=CodeReviewScoringMode.ANY_MATCH)
    assert len(matched) == 2


def test_source_diff_survives_actual_cli_argument_construction(tmp_path):
    import subprocess

    source = '@@ -0,0 +1,3 @@\n+procedure Example()\n+begin\n+    Error("quoted");\n'
    response = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    with (
        patch("bcbench.agent.copilot.cli._find_copilot", return_value="copilot"),
        patch("bcbench.agent.copilot.cli.subprocess.run", return_value=response) as run,
        patch("bcbench.agent.copilot.cli.parse_output", return_value=(None, '[{"pair":1,"match":true}]')),
    ):
        judge_verdicts([(comment("A"), comment("A"))], tmp_path, source_context=source)
    prompt_arg = next(arg for arg in run.call_args.args[0] if arg.startswith("--prompt="))
    encoded = prompt_arg.split("<source-diff>", 1)[1].split("</source-diff>", 1)[0].strip()
    assert json.loads(encoded) == source


def test_invalid_and_timeout_views_do_not_turn_into_correct_silence(tmp_path):
    entry = create_codereview_entry(expected_comments=[comment("A"), comment("B", severity=Severity.LOW)])
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.CODE_REVIEW)
    timeout = CodeReviewResult.create_agent_timeout_failure(context)
    CodeReviewPipeline().save_result(context, timeout)
    result = CodeReviewResult.model_validate_json(next(context.result_dir.glob("*.jsonl")).read_text())
    assert result.timeout
    assert result.scoring_mode == CodeReviewScoringMode.ANY_MATCH
    assert result.missed_comment_count == 1
    assert result.covered_gold_count == 0
    assert result.unscoped_result is not None
    assert result.legacy_result is not None
    assert result.unscoped_result.missed_comment_count == 2
    assert result.legacy_result.timeout
    summary = CodeReviewResultSummary.from_results([result], "timeout")
    assert summary.precision == summary.recall == summary.f1 == 0
    assert summary.expected_comment_count == summary.missed_comment_count == 1
    assert summary.minimum_severity == Severity.MEDIUM
    assert summary.unscoped_summary is not None
    assert summary.unscoped_summary.expected_comment_count == 2
    assert summary.unscoped_summary.mechanical_diagnostics_neutral is True
    assert summary.legacy_summary is not None
    assert summary.legacy_summary.unscoped_summary is not None
