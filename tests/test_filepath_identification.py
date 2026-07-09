from unittest.mock import patch

import bcbench.contamination.runner as runner_mod
from bcbench.contamination.filepath_identification import (
    FilePathIdentificationResult,
    FilePathIdentificationScore,
    aggregate_results,
    build_identification_prompt,
    extract_gold_files,
    normalize_path,
    parse_prediction,
    score_prediction,
    split_by_cutoff,
)
from bcbench.dataset.dataset_entry import _BugFixTestGenBase
from bcbench.exceptions import AgentError
from tests.conftest import create_dataset_entry, create_problem_statement_dir

FULL_PATCH = """diff --git a/App/Foo/Bar.Table.al b/App/Foo/Bar.Table.al
index 111..222 100644
--- a/App/Foo/Bar.Table.al
+++ b/App/Foo/Bar.Table.al
@@ -1,2 +1,2 @@
 field(1; A; Integer) { }
-field(2; B; Integer) { }
+field(2; B; Text[10]) { }
"""


class TestNormalizePath:
    def test_backslashes_become_forward_slashes(self):
        assert normalize_path("App\\Foo\\Bar.Table.al") == "App/Foo/Bar.Table.al"

    def test_strips_dot_and_diff_prefixes(self):
        assert normalize_path("./a/App/Bar.al") == "App/Bar.al"
        assert normalize_path("b/App/Bar.al") == "App/Bar.al"

    def test_strips_quotes_and_whitespace(self):
        assert normalize_path('  "App/Bar.al" ') == "App/Bar.al"


class TestExtractGoldFiles:
    def test_extracts_and_normalizes_paths(self):
        assert extract_gold_files(FULL_PATCH) == ["App/Foo/Bar.Table.al"]

    def test_empty_patch_returns_empty(self):
        assert extract_gold_files("") == []


class TestParsePrediction:
    def test_plain_json_array(self):
        assert parse_prediction('["App/A.al", "App/B.al"]') == ["App/A.al", "App/B.al"]

    def test_fenced_code_block(self):
        assert parse_prediction('```json\n["App/A.al"]\n```') == ["App/A.al"]

    def test_array_of_objects_with_path_key(self):
        assert parse_prediction('[{"path": "App/A.al"}, {"file": "App/B.al"}]') == ["App/A.al", "App/B.al"]

    def test_prose_around_array_is_ignored(self):
        assert parse_prediction('Sure! Here you go: ["App/A.al"] hope that helps') == ["App/A.al"]

    def test_top_k_caps_and_dedupes(self):
        assert parse_prediction('["App/A.al", "App/A.al", "App/B.al", "App/C.al"]', top_k=2) == ["App/A.al", "App/B.al"]

    def test_non_json_returns_empty(self):
        assert parse_prediction("no idea") == []

    def test_non_list_json_returns_empty(self):
        assert parse_prediction('{"path": "App/A.al"}') == []


class TestBuildIdentificationPrompt:
    def test_includes_task_and_top_k(self):
        prompt = build_identification_prompt("Sales header total is wrong", top_k=5)
        assert "Sales header total is wrong" in prompt
        assert "5" in prompt

    def test_task_with_braces_does_not_break(self):
        # AL code contains braces; ensure they survive interpolation verbatim.
        task = "codeunit 50100 X { procedure P() begin end; }"
        assert task in build_identification_prompt(task, top_k=3)


class TestScorePrediction:
    def test_exact_and_basename_hit(self):
        score = score_prediction(["App/Foo/Bar.Table.al"], ["App/Foo/Bar.Table.al"])
        assert score.exact_hit
        assert score.basename_hit
        assert score.exact_recall == 1.0
        assert score.basename_recall == 1.0

    def test_basename_hit_without_exact_when_layout_differs(self):
        score = score_prediction(["Bar.Table.al"], ["App/Foo/Bar.Table.al"])
        assert score.basename_hit
        assert not score.exact_hit
        assert score.basename_recall == 1.0
        assert score.exact_recall == 0.0

    def test_basename_is_case_insensitive(self):
        score = score_prediction(["app/foo/bar.table.al"], ["App/Foo/Bar.Table.al"])
        assert score.basename_hit

    def test_partial_recall_over_multiple_gold_files(self):
        score = score_prediction(["A.al"], ["A.al", "B.al"])
        assert score.basename_recall == 0.5

    def test_no_gold_yields_zero(self):
        score = score_prediction(["A.al"], [])
        assert score.exact_recall == 0.0
        assert score.basename_recall == 0.0
        assert not score.exact_hit
        assert not score.basename_hit


class TestFilePathIdentificationResultBuild:
    def test_scores_against_gold_from_patch(self):
        entry = create_dataset_entry(patch=FULL_PATCH)
        result = FilePathIdentificationResult.build(
            entry=entry,
            model="claude-haiku-4.5",
            category="bug-fix",
            top_k=3,
            predicted_files=["Bar.Table.al"],
        )
        assert result.gold_files == ["App/Foo/Bar.Table.al"]
        assert result.score.basename_hit
        assert result.created_at == entry.created_at


def _result(created_at: str, exact_hit: bool, basename_hit: bool, error: str | None = None) -> FilePathIdentificationResult:
    return FilePathIdentificationResult(
        instance_id="x__y-1",
        model="m",
        category="bug-fix",
        created_at=created_at,
        top_k=3,
        gold_files=["A.al"],
        predicted_files=["A.al"] if basename_hit else [],
        score=FilePathIdentificationScore(
            exact_hit=exact_hit,
            basename_hit=basename_hit,
            exact_recall=1.0 if exact_hit else 0.0,
            basename_recall=1.0 if basename_hit else 0.0,
        ),
        error=error,
    )


class TestAggregateResults:
    def test_rates_exclude_errored_results(self):
        results = [
            _result("2025-01-01", exact_hit=True, basename_hit=True),
            _result("2025-01-02", exact_hit=False, basename_hit=True),
            _result("2025-01-03", exact_hit=False, basename_hit=False, error="boom"),
        ]
        agg = aggregate_results(results)
        assert agg.count == 3
        assert agg.scored == 2
        assert agg.error_count == 1
        assert agg.exact_hit_rate == 0.5
        assert agg.basename_hit_rate == 1.0

    def test_empty_is_zero(self):
        agg = aggregate_results([])
        assert agg.count == 0
        assert agg.basename_hit_rate == 0.0


class TestSplitByCutoff:
    def test_splits_pre_and_post(self):
        pre_result = _result("2024-01-01", exact_hit=True, basename_hit=True)
        post_result = _result("2026-01-01", exact_hit=True, basename_hit=True)
        pre, post = split_by_cutoff([pre_result, post_result], "2025-06-01")
        assert pre == [pre_result]
        assert post == [post_result]

    def test_on_cutoff_is_control(self):
        on_cutoff = _result("2025-06-01", exact_hit=True, basename_hit=True)
        pre, post = split_by_cutoff([on_cutoff], "2025-06-01")
        assert post == [on_cutoff]
        assert pre == []

    def test_unparseable_date_goes_to_pre(self):
        bad = _result("unknown", exact_hit=True, basename_hit=True)
        pre, post = split_by_cutoff([bad], "2025-06-01")
        assert pre == [bad]
        assert post == []


class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path):
        result = _result("2025-01-01", exact_hit=True, basename_hit=True)
        runner_mod.save_identification_result(result, tmp_path / "run")
        loaded = runner_mod.load_identification_results(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].instance_id == result.instance_id


class TestRunFilePathIdentification:
    def test_success_parses_and_saves(self, tmp_path, monkeypatch):
        problem_dir = create_problem_statement_dir(tmp_path, "Sales invoice posting fails")
        entry = create_dataset_entry(patch=FULL_PATCH)
        monkeypatch.setattr(runner_mod, "_run_copilot_context_free", lambda prompt, work_dir, model: '["App/Foo/Bar.Table.al"]')

        with patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_dir)):
            result = runner_mod.run_filepath_identification(entry=entry, model="m", category="bug-fix", top_k=3, output_dir=tmp_path / "out")

        assert result.predicted_files == ["App/Foo/Bar.Table.al"]
        assert result.score.exact_hit
        assert result.error is None
        assert (tmp_path / "out" / f"{entry.instance_id}.file-path-identification.jsonl").exists()

    def test_error_is_captured_and_saved(self, tmp_path, monkeypatch):
        problem_dir = create_problem_statement_dir(tmp_path, "Sales invoice posting fails")
        entry = create_dataset_entry(patch=FULL_PATCH)

        def boom(prompt, work_dir, model):
            raise AgentError("copilot missing")

        monkeypatch.setattr(runner_mod, "_run_copilot_context_free", boom)

        with patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_dir)):
            result = runner_mod.run_filepath_identification(entry=entry, model="m", category="bug-fix", top_k=3, output_dir=tmp_path / "out")

        assert result.error is not None
        assert result.predicted_files == []
        assert (tmp_path / "out" / f"{entry.instance_id}.file-path-identification.jsonl").exists()
