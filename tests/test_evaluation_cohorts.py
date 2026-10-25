import json
from hashlib import sha256
from unittest.mock import PropertyMock, patch

import pytest
import typer
from pydantic import ValidationError

from bcbench.commands import dataset as dataset_commands
from bcbench.dataset import evaluation_cohort_path, load_evaluation_cohort
from bcbench.types import EvaluationCategory, NL2ALDataset
from tests.conftest import create_nl2al_entry

EXPECTED_COMPLETION_POLICY_COHORT = [
    "nl2al__collected-overdue-collection-review-1",
    "nl2al__collected-product-sample-followup-1",
    "nl2al__collected-shipment-complaint-log-1",
    "nl2al__collected-van-mileage-maintenance-1",
    "nl2al__persona-item-low-stock-warning-consultant-2",
    "nl2al__expanded-customer-email-review-invalidation-1",
    "nl2al__expanded-compound-revision-modal-selection-1",
    "nl2al__read-only-compliance-register-permission-set-1",
    "nl2al__expanded-incremental-labor-billing-preview-1",
    "nl2al__expanded-atomic-json-request-parser-1",
    "nl2al__block-purchase-order-without-vendor-vat-2",
    "nl2al__expanded-enum-interface-fee-dispatch-1",
    "nl2al__expanded-customer-csv-export-1",
    "nl2al__expanded-task-sheet-parent-child-lifecycle-1",
    "nl2al__expanded-sales-eligible-variant-picker-1",
    "nl2al__add-industry-field-customer-card-2",
    "nl2al__move-name-customer-card-2",
    "nl2al__expanded-location-bin-pair-integrity-1",
    "nl2al__expanded-company-scoped-data-upgrade-1",
    "nl2al__block-quote-release-over-credit-2",
]


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


def test_load_evaluation_cohort_preserves_order_and_hash(tmp_path):
    entries = [create_nl2al_entry(instance_id="nl2al__one-1"), create_nl2al_entry(instance_id="nl2al__two-1")]
    path, raw = _write_cohort(tmp_path)

    resolved = load_evaluation_cohort(path, dataset=NL2ALDataset.GOLD, available_entries=entries)

    assert resolved.cohort.entries == ["nl2al__one-1", "nl2al__two-1"]
    assert resolved.sha256 == sha256(raw).hexdigest()


def test_checked_in_completion_policy_cohort_is_exact_and_valid():
    dataset_path = EvaluationCategory.NL2AL.dataset_path_for(NL2ALDataset.GOLD)
    available = EvaluationCategory.NL2AL.entry_class.load(dataset_path)
    path = dataset_path.parent / "cohorts" / "55-chat-completion-policy.json"

    resolved = load_evaluation_cohort(path, dataset=NL2ALDataset.GOLD, available_entries=available)

    assert resolved.cohort.entries == EXPECTED_COMPLETION_POLICY_COHORT
    assert len(set(resolved.cohort.entries)) == 20


@pytest.mark.parametrize(
    ("name", "dataset", "entries", "match"),
    [
        ("focus", "gold", [], "at least 1"),
        ("focus", "gold", ["nl2al__one-1", "nl2al__one-1"], "duplicates"),
        ("focus", "challenge", ["nl2al__one-1"], "targets dataset"),
        ("focus", "gold", ["nl2al__missing-1"], "unknown instance IDs"),
    ],
)
def test_load_evaluation_cohort_rejects_invalid_selection(tmp_path, name, dataset, entries, match):
    path, _ = _write_cohort(tmp_path, name=name, dataset=dataset, entries=entries)
    available = [create_nl2al_entry(instance_id="nl2al__one-1")]

    with pytest.raises((ValueError, ValidationError), match=match):
        load_evaluation_cohort(path, dataset=NL2ALDataset.GOLD, available_entries=available)


def test_evaluation_cohort_path_rejects_path_traversal(tmp_path):
    with pytest.raises(ValueError, match="Invalid evaluation cohort name"):
        evaluation_cohort_path(tmp_path, "../focus")


def test_dataset_list_emits_validated_cohort_and_repetition_outputs(tmp_path):
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
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=dataset_path),
        patch.object(EvaluationCategory, "entry_class", new_callable=PropertyMock, return_value=EntryClass),
        patch.object(dataset_commands, "write_step_outputs") as write_outputs,
    ):
        dataset_commands.list_entries(
            category=EvaluationCategory.NL2AL,
            github_output="entries",
            modified_only=False,
            test_run=False,
            dataset=NL2ALDataset.GOLD,
            cohort="focus",
            repeat_count=2,
        )

    write_outputs.assert_called_once_with(
        {
            "entries": json.dumps(["nl2al__one-1", "nl2al__two-1"]),
            "cohort-name": "focus",
            "cohort-sha256": sha256(raw).hexdigest(),
            "repetition-count": "2",
            "repetitions": "[1, 2]",
        }
    )


def test_dataset_list_rejects_cohort_with_test_run():
    with pytest.raises(typer.BadParameter, match="cannot be combined"):
        dataset_commands.list_entries(
            category=EvaluationCategory.NL2AL,
            github_output=None,
            modified_only=False,
            dataset=NL2ALDataset.GOLD,
            cohort="focus",
            test_run=True,
            repeat_count=1,
        )
