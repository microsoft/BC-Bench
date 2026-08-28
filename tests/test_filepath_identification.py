import pytest

import bcbench.contamination.runner as runner_mod
from bcbench.contamination.filepath_identification import (
    FilePathIdentificationResult,
    build_identification_prompt,
    matches_any_gold_path,
    parse_prediction,
)
from bcbench.types import AgentMetrics, EvaluationCategory
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


class TestParsePrediction:
    def test_extracts_one_path_from_paper_response_format(self):
        response = """DISCUSSION
The issue concerns table A.
RESPONSE
```
App/A.al
```"""
        assert parse_prediction(response) == ["App/A.al"]

    def test_tolerates_decorated_headers_and_trailing_prose(self):
        response = """**DISCUSSION:**
The issue concerns table A.
**RESPONSE:**
```text
App/A.al
```
Hope this helps!"""
        assert parse_prediction(response) == ["App/A.al"]

    def test_ignores_a_code_block_used_in_the_discussion(self):
        response = """DISCUSSION
Relevant snippet:
```
field(2; B; Integer) { }
```
RESPONSE
```
App/A.al
```"""
        assert parse_prediction(response) == ["App/A.al"]

    def test_extracts_path_from_inline_fence(self):
        assert parse_prediction("RESPONSE\n```App/A.al```") == ["App/A.al"]

    def test_uses_first_fenced_block_after_response(self):
        response = """RESPONSE
```
App/A.al
```
Additional example:
```
App/B.al
```"""
        assert parse_prediction(response) == ["App/A.al"]

    @pytest.mark.parametrize(
        ("raw_path", "expected"),
        [
            ("`App/A.al`", "App/A.al"),
            ("App\\A.al", "App/A.al"),
            ("./App/A.al", "App/A.al"),
            ("a/App/A.al", "App/A.al"),
            ('"App/A.al"', "App/A.al"),
        ],
    )
    def test_normalizes_prediction_presentation(self, raw_path, expected):
        assert parse_prediction(f"RESPONSE\n```\n{raw_path}\n```") == [expected]

    def test_multiple_paths_raise_for_one_shot_probe(self):
        response = """DISCUSSION
Two files seem relevant.
RESPONSE
```
App/A.al
App/B.al
```"""
        with pytest.raises(ValueError, match="exactly one path"):
            parse_prediction(response)

    def test_answer_without_fenced_block_raises(self):
        with pytest.raises(ValueError, match="fenced code block"):
            parse_prediction("DISCUSSION\nFound it.\nRESPONSE\nApp/A.al")

    def test_empty_output_raises(self):
        with pytest.raises(ValueError, match="fenced code block"):
            parse_prediction("")


class TestBuildIdentificationPrompt:
    def test_requests_exactly_one_path(self):
        prompt = build_identification_prompt("Sales header total is wrong")
        assert "Sales header total is wrong" in prompt
        assert "The code base is: microsoft/BCApps." in prompt
        assert "one discussion and one response" in prompt
        assert "provide a file-path of the .al file" in prompt

    def test_task_with_braces_does_not_break(self):
        task = "codeunit 50100 X { procedure P() begin end; }"
        assert task in build_identification_prompt(task)


class TestMatchesAnyGoldPath:
    def test_identical_path_matches(self):
        assert matches_any_gold_path(["App/Foo/Bar.Table.al"], ["App/Foo/Bar.Table.al"])

    def test_basename_only_does_not_match(self):
        assert not matches_any_gold_path(["Bar.Table.al"], ["App/Foo/Bar.Table.al"])

    def test_separator_variant_does_not_match(self):
        assert not matches_any_gold_path(["App\\Foo\\Bar.Table.al"], ["App/Foo/Bar.Table.al"])

    def test_one_prediction_can_match_any_gold_path(self):
        assert matches_any_gold_path(["App/B.al"], ["App/A.al", "App/B.al"])

    def test_no_gold_does_not_match(self):
        assert not matches_any_gold_path(["App/A.al"], [])


def _result(matches_any_gold_path: bool) -> FilePathIdentificationResult:
    return FilePathIdentificationResult(
        instance_id="x__y-1",
        model="m",
        category=EvaluationCategory.BUG_FIX,
        gold_files=["A.al"],
        predicted_files=["A.al"] if matches_any_gold_path else ["B.al"],
        matches_any_gold_path=matches_any_gold_path,
    )


class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_path):
        result = _result(matches_any_gold_path=True)
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        runner_mod.save_identification_result(result, run_dir)
        loaded = runner_mod.load_identification_results(tmp_path)
        assert loaded == [result]


class TestRunFilePathIdentification:
    def test_success_uses_shared_copilot_invocation_and_saves(self, tmp_path, monkeypatch):
        entry = create_dataset_entry(patch=FULL_PATCH)
        problem_dir = create_problem_statement_dir(tmp_path, "Sales invoice posting fails")
        monkeypatch.setattr(type(entry), "problem_statement_dir", property(lambda self: problem_dir))
        metrics = AgentMetrics(execution_time=1.0)
        raw_output = """DISCUSSION
This bug concerns the Bar table.
RESPONSE
```
App/Foo/Bar.Table.al
```"""
        monkeypatch.setattr(runner_mod, "invoke_copilot", lambda **_kwargs: (metrics, raw_output))
        result_dir = tmp_path / "out"
        result_dir.mkdir()

        result = runner_mod.run_filepath_identification(entry=entry, model="m", result_dir=result_dir)

        assert result.predicted_files == ["App/Foo/Bar.Table.al"]
        assert result.matches_any_gold_path
        assert result.metrics == metrics
        assert (result_dir / f"{entry.instance_id}.filepath-identification.jsonl").exists()

    def test_unparseable_answer_logs_raw_output_without_saving(self, tmp_path, monkeypatch, caplog):
        entry = create_dataset_entry(patch=FULL_PATCH)
        problem_dir = create_problem_statement_dir(tmp_path, "Sales invoice posting fails")
        monkeypatch.setattr(type(entry), "problem_statement_dir", property(lambda self: problem_dir))
        raw_output = "I cannot determine the file."
        monkeypatch.setattr(runner_mod, "invoke_copilot", lambda **_kwargs: (None, raw_output))
        result_dir = tmp_path / "out"
        result_dir.mkdir()

        with pytest.raises(ValueError, match="fenced code block"):
            runner_mod.run_filepath_identification(entry=entry, model="m", result_dir=result_dir)

        assert raw_output in caplog.text
        assert not list(result_dir.iterdir())

    def test_invocation_errors_propagate_without_saving(self, tmp_path, monkeypatch):
        entry = create_dataset_entry(patch=FULL_PATCH)
        problem_dir = create_problem_statement_dir(tmp_path, "Sales invoice posting fails")
        monkeypatch.setattr(type(entry), "problem_statement_dir", property(lambda self: problem_dir))

        def fail(**_kwargs):
            raise RuntimeError("copilot missing")

        monkeypatch.setattr(runner_mod, "invoke_copilot", fail)

        with pytest.raises(RuntimeError, match="copilot missing"):
            runner_mod.run_filepath_identification(entry=entry, model="m", result_dir=tmp_path / "out")

        assert not (tmp_path / "out").exists()
