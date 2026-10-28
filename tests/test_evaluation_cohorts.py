import json
from hashlib import sha256
from unittest.mock import PropertyMock, patch

import pytest
import typer
from pydantic import ValidationError

from bcbench.commands import dataset as dataset_commands
from bcbench.dataset import NL2ALEntry, load_evaluation_cohort
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, DatasetTier, EvaluationCategory, EvaluationContext
from tests.conftest import create_nl2al_entry

GOLD_COHORT = "bcal-staged-policy-ablation-gold"
CHALLENGE_COHORT = "bcal-staged-policy-ablation-challenge"


def _write_cohort(tmp_path, *, name="focus", dataset="gold", entries=None):
    cohort_dir = tmp_path / "cohorts"
    cohort_dir.mkdir(exist_ok=True)
    path = cohort_dir / f"{name}.json"
    payload = {
        "name": name,
        "dataset": dataset,
        "entries": entries if entries is not None else ["nl2al__one-1", "nl2al__two-1"],
    }
    raw = json.dumps(payload, indent=2).encode()
    path.write_bytes(raw)
    return path, raw


def test_legacy_cohort_preserves_order_and_raw_hash(tmp_path):
    entries = [create_nl2al_entry(instance_id="nl2al__one-1"), create_nl2al_entry(instance_id="nl2al__two-1")]
    path, raw = _write_cohort(tmp_path)

    resolved = load_evaluation_cohort(path, dataset=DatasetTier.GOLD, available_entries=entries)

    assert resolved.cohort.entry_ids == ["nl2al__one-1", "nl2al__two-1"]
    assert resolved.cohort.entries == ["nl2al__one-1", "nl2al__two-1"]
    assert resolved.sha256 == sha256(raw).hexdigest()


def test_tagged_cohort_parses_case_metadata(tmp_path):
    tagged = {
        "instance_id": "nl2al__one-1",
        "applicability": ["8656", "8669"],
        "role": "target",
        "notes": "Original-problem case.",
    }
    path, raw = _write_cohort(tmp_path, entries=[tagged, "nl2al__two-1"])
    entries = [create_nl2al_entry(instance_id="nl2al__one-1"), create_nl2al_entry(instance_id="nl2al__two-1")]

    resolved = load_evaluation_cohort(path, dataset=DatasetTier.GOLD, available_entries=entries)

    assert resolved.cohort.entry_ids == ["nl2al__one-1", "nl2al__two-1"]
    assert resolved.sha256 == sha256(raw).hexdigest()
    metadata = resolved.cohort.metadata_for("nl2al__one-1")
    assert metadata is not None
    assert metadata.applicability == ["8656", "8669"]
    assert metadata.role == "target"


@pytest.mark.parametrize(
    ("entries", "match"),
    [
        ([], "at least 1"),
        (["nl2al__one-1", {"instance_id": "nl2al__one-1"}], "duplicates"),
        ([{"instance_id": "nl2al__one-1", "applicability": ["8656", "8656"]}], "applicability"),
        ([{"instance_id": "nl2al__one-1", "applicability": ["9999"]}], "Input should be"),
        (["nl2al__missing-1"], "unknown instance IDs"),
    ],
)
def test_tagged_cohort_rejects_invalid_entries(tmp_path, entries, match):
    path, _ = _write_cohort(tmp_path, entries=entries)

    with pytest.raises((ValueError, ValidationError), match=match):
        load_evaluation_cohort(path, dataset=DatasetTier.GOLD, available_entries=[create_nl2al_entry(instance_id="nl2al__one-1")])


def test_checked_in_staged_cohorts_are_valid_and_have_14_cases_each():
    for tier, cohort_name in ((DatasetTier.GOLD, GOLD_COHORT), (DatasetTier.CHALLENGE, CHALLENGE_COHORT)):
        dataset_path = EvaluationCategory.NL2AL.dataset_path(tier)
        available = EvaluationCategory.NL2AL.entry_class.load(dataset_path)

        resolved = load_evaluation_cohort(dataset_path.parent / "cohorts" / f"{cohort_name}.json", dataset=tier, available_entries=available)

        assert len(resolved.cohort.entry_ids) == 14
        assert len(set(resolved.cohort.entry_ids)) == 14
        assert all(not isinstance(entry, str) for entry in resolved.cohort.entries)


def test_dataset_list_emits_resolved_ids_hash_and_repetitions(tmp_path):
    entries = [create_nl2al_entry(instance_id="nl2al__one-1"), create_nl2al_entry(instance_id="nl2al__two-1")]
    dataset_path = tmp_path / "nl2al.jsonl"
    _, raw = _write_cohort(tmp_path)

    class EntryClass:
        @staticmethod
        def load(resolved_path, random=None):
            assert resolved_path == dataset_path
            assert random is None
            return entries

    with (
        patch.object(EvaluationCategory, "dataset_path", return_value=dataset_path),
        patch.object(EvaluationCategory, "entry_class", new_callable=PropertyMock, return_value=EntryClass),
        patch.object(dataset_commands, "write_step_outputs") as write_outputs,
    ):
        dataset_commands.list_entries(
            category=EvaluationCategory.NL2AL,
            tier=DatasetTier.GOLD,
            github_output="entries",
            cohort="focus",
            repeat_count=3,
        )

    write_outputs.assert_called_once_with(
        {
            "entries": json.dumps(["nl2al__one-1", "nl2al__two-1"]),
            "cohort-name": "focus",
            "cohort-sha256": sha256(raw).hexdigest(),
            "repetition-count": "3",
            "repetitions": "[1, 2, 3]",
        }
    )


def test_dataset_list_rejects_cohort_with_test_run():
    with pytest.raises(typer.BadParameter, match="cannot be combined"):
        dataset_commands.list_entries(
            category=EvaluationCategory.NL2AL,
            tier=DatasetTier.GOLD,
            cohort="focus",
            test_run=True,
        )


def test_case_and_study_metadata_propagate_to_result_and_bceval(tmp_path):
    entry = create_nl2al_entry(instance_id="nl2al__one-1")
    context = EvaluationContext(
        entry=entry,
        repo_path=tmp_path,
        result_dir=tmp_path,
        agent_name=AgentHarness.BCAL,
        model="fixed-model",
        category=EvaluationCategory.NL2AL,
        cohort_name="focus",
        cohort_sha256="a" * 64,
        cohort_applicability=["8656", "8735"],
        cohort_role="target",
        cohort_notes="Original-problem case.",
        repetition_index=2,
        repetition_count=3,
        study_id="bcal-policy-ablation",
        variant_id="A-off",
        bcal_common_base_sha="b" * 40,
        bcal_variant_patch_sha="c" * 40,
    )
    result = JudgeBasedEvaluationResult.create_raw(context, output="patch")
    result.save(tmp_path, "raw.jsonl")

    saved = json.loads((tmp_path / "raw.jsonl").read_text(encoding="utf-8"))
    assert saved["cohort_applicability"] == ["8656", "8735"]
    assert saved["variant_id"] == "A-off"

    with patch.object(NL2ALEntry, "load", return_value=[entry]):
        write_bceval_results(
            results=[result],
            out_dir=tmp_path,
            run_id="run",
            output_filename="bceval.jsonl",
            category=EvaluationCategory.NL2AL,
        )

    metadata = json.loads((tmp_path / "bceval.jsonl").read_text(encoding="utf-8"))["metadata"]
    assert metadata["cohort_applicability"] == ["8656", "8735"]
    assert metadata["cohort_role"] == "target"
    assert metadata["repetition_index"] == 2
    assert metadata["study_id"] == "bcal-policy-ablation"
    assert metadata["variant_id"] == "A-off"
    assert metadata["bcal_common_base_sha"] == "b" * 40
    assert metadata["bcal_variant_patch_sha"] == "c" * 40
