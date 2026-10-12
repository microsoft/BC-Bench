import json

import pytest
import typer

from bcbench.commands.result import _validate_selected_coverage, result_summarize
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.types import EvaluationCategory
from tests.conftest import create_evaluation_context, create_nl2al_entry


def _result(tmp_path, instance_id: str, *, failure: bool = False):
    entry = create_nl2al_entry(instance_id=instance_id)
    context = create_evaluation_context(tmp_path, entry=entry, category=EvaluationCategory.NL2AL)
    if failure:
        return JudgeBasedEvaluationResult.create_failure(context, "", "agent failed")
    return JudgeBasedEvaluationResult.create_raw(context, "AL")


@pytest.mark.parametrize("kind", ["missing", "unexpected", "duplicate"])
def test_selected_matrix_coverage_rejects_identity_gaps(tmp_path, kind):
    expected_id = "nl2al__expected-case-1"
    result = _result(tmp_path, expected_id)
    expected = [expected_id]
    results = [result]

    if kind == "missing":
        expected.append("nl2al__missing-case-1")
    elif kind == "unexpected":
        expected = ["nl2al__different-case-1"]
    else:
        results.append(result)

    with pytest.raises(typer.Exit):
        _validate_selected_coverage(results, json.dumps(expected), tmp_path)

    coverage = json.loads((tmp_path / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage[f"{kind}_entries"]


def test_valid_failure_result_counts_as_present(tmp_path):
    instance_id = "nl2al__failed-case-1"
    _validate_selected_coverage([_result(tmp_path, instance_id, failure=True)], json.dumps([instance_id]), tmp_path)

    coverage = json.loads((tmp_path / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage == {
        "expected_entry_count": 1,
        "produced_entry_count": 1,
        "missing_entries": [],
        "unexpected_entries": [],
        "duplicate_entries": [],
    }


def test_selected_smoke_subset_only_requires_selected_ids(tmp_path):
    selected_id = "nl2al__selected-case-1"
    _validate_selected_coverage([_result(tmp_path, selected_id)], json.dumps([selected_id]), tmp_path)

    coverage = json.loads((tmp_path / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage["expected_entry_count"] == 1
    assert coverage["missing_entries"] == []


def test_expected_matrix_ids_must_be_unique(tmp_path):
    result = _result(tmp_path, "nl2al__selected-case-1")

    with pytest.raises(typer.BadParameter, match="duplicate IDs"):
        _validate_selected_coverage([result], '["nl2al__selected-case-1", "nl2al__selected-case-1"]', tmp_path)


def test_missing_result_directory_still_writes_complete_coverage_diagnostics(tmp_path):
    instance_id = "nl2al__missing-case-1"

    with pytest.raises(typer.Exit):
        result_summarize(
            run_id="run",
            category=EvaluationCategory.NL2AL,
            result_dir=tmp_path,
            expected_entries=json.dumps([instance_id]),
        )

    coverage = json.loads((tmp_path / "run" / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage["missing_entries"] == [instance_id]
