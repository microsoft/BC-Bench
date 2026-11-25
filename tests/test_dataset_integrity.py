"""Tests validating integrity of the bcbench.jsonl dataset entries.

These tests ensure the dataset follows expected conventions and doesn't contain
common mistakes that could affect evaluation accuracy.
"""

import re

import pytest

from bcbench.dataset.extensibility_request import ExtRequestTriageEntry
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry

VALID_W1_PATCH = "diff --git a/App/Layers/W1/BaseApp/Test.al b/App/Layers/W1/BaseApp/Test.al\n+test"
INVALID_IT_PATCH = "diff --git a/App/Layers/IT/BaseApp/Test.al b/App/Layers/IT/BaseApp/Test.al\n+test"
BASEAPP_PROJECT_PATHS = ["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\SCM"]
SHOPIFY_PROJECT_PATHS = ["App\\Apps\\W1\\Shopify\\app", "App\\Apps\\W1\\Shopify\\test"]


def test_triage_dataset_has_unique_entries_and_request_snapshots():
    dataset_path = EvaluationCategory.EXT_REQUEST_TRIAGE.dataset_path()
    entries = [ExtRequestTriageEntry.model_validate_json(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert entries
    assert len({entry.instance_id for entry in entries}) == len(entries)
    assert len({(entry.repo, entry.base_commit, entry.get_task()) for entry in entries}) == len(entries)


def test_bcapps_triage_snapshots_do_not_commit_to_requester_implementation():
    dataset_path = EvaluationCategory.EXT_REQUEST_TRIAGE.dataset_path()
    entries = [ExtRequestTriageEntry.model_validate_json(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    bcapps_entries = [entry for entry in entries if entry.repo == "microsoft/BCApps"]

    assert bcapps_entries
    for entry in bcapps_entries:
        assert not re.search(r"(?m)^\s*-\s*\[[xX]\]\s*I will provide the implementation", entry.get_task()), entry.instance_id


class TestPatchLayerValidation:
    def test_baseapp_with_w1_patch_is_valid(self):
        entry = create_dataset_entry(
            project_paths=BASEAPP_PROJECT_PATHS,
            patch=VALID_W1_PATCH,
            test_patch=VALID_W1_PATCH,
        )
        assert entry is not None

    def test_baseapp_with_non_w1_patch_raises_error(self):
        with pytest.raises(ValueError, match="non-W1 layer 'IT'"):
            create_dataset_entry(
                project_paths=BASEAPP_PROJECT_PATHS,
                patch=INVALID_IT_PATCH,
            )

    def test_baseapp_with_non_w1_test_patch_raises_error(self):
        with pytest.raises(ValueError, match="non-W1 layer 'IT'"):
            create_dataset_entry(
                project_paths=BASEAPP_PROJECT_PATHS,
                patch=VALID_W1_PATCH,
                test_patch=INVALID_IT_PATCH,
            )

    def test_non_baseapp_project_allows_any_patch(self):
        entry = create_dataset_entry(
            project_paths=SHOPIFY_PROJECT_PATHS,
            patch=INVALID_IT_PATCH,
        )
        assert entry is not None
