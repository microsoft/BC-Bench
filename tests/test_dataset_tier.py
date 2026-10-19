import json

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.dataset import NL2ALEntry
from bcbench.dataset.dataset_entry import EntryMetadata
from bcbench.exceptions import EntryNotFoundError
from bcbench.results import BaseEvaluationResult, JudgeBasedEvaluationResult
from bcbench.types import DatasetTier, EvaluationCategory
from tests.conftest import create_evaluation_context, create_nl2al_entry


@pytest.fixture
def tiered_dataset(tmp_path):
    gold = create_nl2al_entry(instance_id="nl2al__gold-1")
    challenge = create_nl2al_entry(instance_id="nl2al__challenge-1").model_copy(update={"metadata": EntryMetadata(tier=DatasetTier.CHALLENGE)})
    path = tmp_path / "nl2al.jsonl"
    path.write_text(gold.model_dump_json() + "\n" + challenge.model_dump_json() + "\n", encoding="utf-8")
    return path


def test_entries_without_tier_are_gold():
    assert EntryMetadata().tier is DatasetTier.GOLD


def test_load_filters_on_tier(tiered_dataset):
    assert [e.instance_id for e in NL2ALEntry.load(tiered_dataset)] == ["nl2al__gold-1", "nl2al__challenge-1"]
    assert [e.instance_id for e in NL2ALEntry.load(tiered_dataset, tier=DatasetTier.GOLD)] == ["nl2al__gold-1"]
    assert [e.instance_id for e in NL2ALEntry.load(tiered_dataset, tier=DatasetTier.CHALLENGE)] == ["nl2al__challenge-1"]


def test_load_by_id_respects_tier(tiered_dataset):
    with pytest.raises(EntryNotFoundError):
        NL2ALEntry.load(tiered_dataset, entry_id="nl2al__challenge-1", tier=DatasetTier.GOLD)


@pytest.mark.parametrize("tier", list(DatasetTier))
def test_dataset_list_defaults_to_gold_and_selects_tier(tier: DatasetTier):
    expected = NL2ALEntry.load(EvaluationCategory.NL2AL.dataset_path, tier=tier)
    args = ["dataset", "list", "--category", "nl2al"] + ([] if tier is DatasetTier.GOLD else ["--tier", tier])

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert expected
    assert f"Found {len(expected)} entry(ies)" in result.output


def test_result_records_context_tier_and_legacy_results_default_to_gold(tmp_path):
    context = create_evaluation_context(tmp_path, entry=create_nl2al_entry(), category=EvaluationCategory.NL2AL)
    context.tier = DatasetTier.CHALLENGE

    payload = JudgeBasedEvaluationResult.create_raw(context, output="codeunit 50100 X {}").model_dump(mode="json")

    assert BaseEvaluationResult.from_json(payload).tier is DatasetTier.CHALLENGE
    del payload["tier"]
    assert BaseEvaluationResult.from_json(json.loads(json.dumps(payload))).tier is DatasetTier.GOLD
