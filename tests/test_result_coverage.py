import json

import pytest
import typer

from bcbench.commands.result import _validate_selected_coverage
from tests.conftest import create_bugfix_result


def test_selected_coverage_writes_complete_diagnostics(tmp_path):
    results = [create_bugfix_result(instance_id="one"), create_bugfix_result(instance_id="two")]

    _validate_selected_coverage(results, '["one", "two"]', tmp_path)

    coverage = json.loads((tmp_path / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage == {
        "expected_entry_count": 2,
        "produced_entry_count": 2,
        "missing_entries": [],
        "unexpected_entries": [],
        "duplicate_entries": [],
    }


def test_selected_coverage_rejects_missing_rows_without_counting_them_as_improvement(tmp_path):
    with pytest.raises(typer.Exit):
        _validate_selected_coverage([create_bugfix_result(instance_id="one")], '["one", "two"]', tmp_path)

    coverage = json.loads((tmp_path / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage["missing_entries"] == ["two"]


def test_selected_coverage_can_publish_available_rows_with_explicit_missing_diagnostics(tmp_path):
    _validate_selected_coverage([create_bugfix_result(instance_id="one")], '["one", "two"]', tmp_path, allow_incomplete=True)

    coverage = json.loads((tmp_path / "evaluation_coverage.json").read_text(encoding="utf-8"))
    assert coverage["produced_entry_count"] == 1
    assert coverage["missing_entries"] == ["two"]
