import json

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.dataset import NL2ALEntry
from bcbench.results import BaseEvaluationResult, JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import DatasetTier, EvaluationCategory
from tests.conftest import create_evaluation_context

NL2AL = EvaluationCategory.NL2AL


@pytest.mark.parametrize("category", list(EvaluationCategory))
def test_gold_tier_is_the_category_dataset(category: EvaluationCategory):
    assert category.dataset_path_for(DatasetTier.GOLD) == category.dataset_path


@pytest.mark.parametrize("category", [c for c in EvaluationCategory if c is not NL2AL])
def test_categories_without_challenge_dataset_reject_challenge_tier(category: EvaluationCategory):
    assert category.challenge_dataset_path is None
    with pytest.raises(ValueError, match="has no challenge dataset"):
        category.dataset_path_for(DatasetTier.CHALLENGE)


def test_nl2al_challenge_dataset_is_separate_from_gold():
    gold_ids = {e.instance_id for e in NL2ALEntry.load(NL2AL.dataset_path_for(DatasetTier.GOLD))}
    challenge_ids = {e.instance_id for e in NL2ALEntry.load(NL2AL.dataset_path_for(DatasetTier.CHALLENGE))}

    assert NL2AL.challenge_dataset_path is not None
    assert NL2AL.challenge_dataset_path != NL2AL.dataset_path
    assert gold_ids
    assert challenge_ids
    assert gold_ids.isdisjoint(challenge_ids)


@pytest.mark.parametrize("tier", list(DatasetTier))
def test_dataset_list_defaults_to_gold_and_selects_tier(tier: DatasetTier):
    expected = NL2ALEntry.load(NL2AL.dataset_path_for(tier))
    args = ["dataset", "list", "--category", "nl2al"] + ([] if tier is DatasetTier.GOLD else ["--tier", tier])

    result = CliRunner().invoke(app, args)

    assert result.exit_code == 0, result.output
    assert f"Found {len(expected)} entry(ies)" in result.output


def test_result_records_context_tier_and_legacy_results_default_to_gold(tmp_path):
    entry = NL2ALEntry.load(NL2AL.dataset_path_for(DatasetTier.CHALLENGE))[0]
    context = create_evaluation_context(tmp_path, entry=entry, category=NL2AL)
    context.tier = DatasetTier.CHALLENGE

    payload = JudgeBasedEvaluationResult.create_raw(context, output="codeunit 50100 X {}").model_dump(mode="json")

    assert BaseEvaluationResult.from_json(payload).tier is DatasetTier.CHALLENGE
    del payload["tier"]
    assert BaseEvaluationResult.from_json(json.loads(json.dumps(payload))).tier is DatasetTier.GOLD


def test_bceval_export_resolves_each_result_from_its_tier_dataset(tmp_path):
    results: list[BaseEvaluationResult] = []
    for tier in DatasetTier:
        entry = NL2ALEntry.load(NL2AL.dataset_path_for(tier))[0]
        context = create_evaluation_context(tmp_path, entry=entry, category=NL2AL)
        context.tier = tier
        results.append(JudgeBasedEvaluationResult.create_raw(context, output="codeunit 50100 X {}"))

    write_bceval_results(results, tmp_path, "run", "bceval.jsonl", NL2AL)

    rows = [json.loads(line) for line in (tmp_path / "bceval.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(row["id"], row["metadata"]["tier"]) for row in rows] == [(r.instance_id, r.tier) for r in results]
