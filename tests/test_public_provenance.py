import json
from unittest.mock import patch

import pytest

from bcbench.results import BaseEvaluationResult, EvaluationResultSummary
from bcbench.results.provenance import make_run_identity
from bcbench.types import EvaluationCategory
from tests.conftest import create_bugfix_result


def test_public_summary_uses_execution_provenance_not_current_dataset_or_version(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"sample": 1}\n', encoding="utf-8")
    recorded = make_run_identity(EvaluationCategory.BUG_FIX, dataset)
    original = create_bugfix_result().model_copy(update={"benchmark_version": "0.13.0", "provenance": recorded})
    original.save(tmp_path, "result.jsonl")
    dataset.write_text('{"sample": 2}\n', encoding="utf-8")

    with patch("bcbench.results.summary.get_benchmark_version", return_value="99.0.0"):
        reloaded = BaseEvaluationResult.from_json(json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8")))
        summary = EvaluationResultSummary.from_results([reloaded], "example-run")

    assert summary.benchmark_version == "0.13.0"
    assert summary.provenance == recorded
    assert summary.provenance is not None
    assert summary.provenance.data_revision != make_run_identity(EvaluationCategory.BUG_FIX, dataset).data_revision


def test_public_summary_rejects_mixed_execution_provenance(tmp_path):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("first", encoding="utf-8")
    first = create_bugfix_result().model_copy(update={"provenance": make_run_identity(EvaluationCategory.BUG_FIX, dataset)})
    dataset.write_text("second", encoding="utf-8")
    second = create_bugfix_result(instance_id="sample__case-2").model_copy(update={"provenance": make_run_identity(EvaluationCategory.BUG_FIX, dataset)})
    with pytest.raises(ValueError, match="different runs"):
        EvaluationResultSummary.from_results([first, second], "example-run")
