"""Tests for dataset entry load, save, and property operations."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.dataset import BugFixEntry, TestGenEntry
from bcbench.exceptions import EntryNotFoundError
from tests.conftest import (
    VALID_BASE_COMMIT,
    VALID_CREATED_AT,
    VALID_ENVIRONMENT_VERSION,
    VALID_INSTANCE_ID,
    VALID_PATCH,
    VALID_PROJECT_PATHS,
    VALID_TEST_PATCH,
    create_dataset_entry,
    create_dataset_file,
    create_problem_statement_dir,
)


def _make_testgen_entry(**kwargs) -> TestGenEntry:
    defaults: dict = {
        "instance_id": VALID_INSTANCE_ID,
        "repo": "microsoftInternal/NAV",
        "base_commit": VALID_BASE_COMMIT,
        "environment_setup_version": VALID_ENVIRONMENT_VERSION,
        "project_paths": VALID_PROJECT_PATHS,
        "patch": VALID_PATCH,
        "test_patch": VALID_TEST_PATCH,
        "created_at": VALID_CREATED_AT,
        "fail_to_pass": [{"codeunitID": 100, "functionName": ["TestFunc"]}],
    }
    defaults.update(kwargs)
    return TestGenEntry(**defaults)


class TestBugFixEntryGetExpectedOutput:
    def test_returns_patch(self):
        entry = create_dataset_entry()
        assert entry.get_expected_output() == VALID_PATCH


class TestTestGenEntryGetExpectedOutput:
    def test_returns_test_patch(self):
        entry = _make_testgen_entry()
        assert entry.get_expected_output() == VALID_TEST_PATCH


class TestDatasetEntryLoad:
    def test_load_all_entries(self, tmp_path):
        entries = [
            create_dataset_entry(instance_id="microsoftInternal__NAV-111111"),
            create_dataset_entry(instance_id="microsoftInternal__NAV-222222"),
        ]
        dataset_path = create_dataset_file(tmp_path, entries)

        loaded = BugFixEntry.load(dataset_path)
        assert len(loaded) == 2

    def test_load_by_entry_id_returns_match(self, tmp_path):
        entries = [
            create_dataset_entry(instance_id="microsoftInternal__NAV-111111"),
            create_dataset_entry(instance_id="microsoftInternal__NAV-222222"),
        ]
        dataset_path = create_dataset_file(tmp_path, entries)

        loaded = BugFixEntry.load(dataset_path, entry_id="microsoftInternal__NAV-111111")
        assert len(loaded) == 1
        assert loaded[0].instance_id == "microsoftInternal__NAV-111111"

    def test_load_by_entry_id_not_found_raises(self, tmp_path):
        dataset_path = create_dataset_file(tmp_path)

        with pytest.raises(EntryNotFoundError):
            BugFixEntry.load(dataset_path, entry_id="microsoftInternal__NAV-999999")

    def test_load_skips_blank_lines(self, tmp_path):
        entry = create_dataset_entry()
        dataset_path = tmp_path / "dataset.jsonl"
        entry_dict = {
            "instance_id": entry.instance_id,
            "repo": entry.repo,
            "base_commit": entry.base_commit,
            "environment_setup_version": entry.environment_setup_version,
            "FAIL_TO_PASS": [{"codeunitID": t.codeunitID, "functionName": list(t.functionName)} for t in entry.fail_to_pass],
            "PASS_TO_PASS": [],
            "project_paths": entry.project_paths,
            "patch": entry.patch,
            "test_patch": entry.test_patch,
            "created_at": entry.created_at,
        }
        # Write with blank lines interspersed
        with open(dataset_path, "w") as f:
            f.write("\n")
            f.write(json.dumps(entry_dict) + "\n")
            f.write("\n")

        loaded = BugFixEntry.load(dataset_path)
        assert len(loaded) == 1

    def test_load_with_random_returns_sample(self, tmp_path):
        entries = [create_dataset_entry(instance_id=f"microsoftInternal__NAV-{100000 + i}") for i in range(10)]
        dataset_path = create_dataset_file(tmp_path, entries)

        loaded = BugFixEntry.load(dataset_path, random=3)
        assert len(loaded) == 3

    def test_load_random_capped_at_total(self, tmp_path):
        entries = [create_dataset_entry(instance_id=f"microsoftInternal__NAV-{100000 + i}") for i in range(3)]
        dataset_path = create_dataset_file(tmp_path, entries)

        loaded = BugFixEntry.load(dataset_path, random=100)
        assert len(loaded) == 3

    def test_load_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            BugFixEntry.load(tmp_path / "nonexistent.jsonl")


class TestDatasetEntrySaveToFile:
    def test_save_to_file_creates_file(self, tmp_path):
        entry = create_dataset_entry()
        filepath = tmp_path / "output.jsonl"

        entry.save_to_file(filepath)

        assert filepath.exists()

    def test_save_to_file_writes_valid_json(self, tmp_path):
        entry = create_dataset_entry()
        filepath = tmp_path / "output.jsonl"

        entry.save_to_file(filepath)

        content = filepath.read_text()
        parsed = json.loads(content.strip())
        assert parsed["instance_id"] == entry.instance_id

    def test_save_to_file_uses_aliases(self, tmp_path):
        entry = create_dataset_entry()
        filepath = tmp_path / "output.jsonl"

        entry.save_to_file(filepath)

        content = filepath.read_text()
        parsed = json.loads(content.strip())
        # Should use alias "FAIL_TO_PASS" not "fail_to_pass"
        assert "FAIL_TO_PASS" in parsed

    def test_save_to_file_appends(self, tmp_path):
        entry1 = create_dataset_entry(instance_id="microsoftInternal__NAV-111111")
        entry2 = create_dataset_entry(instance_id="microsoftInternal__NAV-222222")
        filepath = tmp_path / "output.jsonl"

        entry1.save_to_file(filepath)
        entry2.save_to_file(filepath)

        lines = [line for line in filepath.read_text().splitlines() if line.strip()]
        assert len(lines) == 2

    def test_save_to_file_creates_parent_dirs(self, tmp_path):
        entry = create_dataset_entry()
        filepath = tmp_path / "nested" / "deep" / "output.jsonl"

        entry.save_to_file(filepath)

        assert filepath.exists()


class TestExtractProjectNameEdgeCases:
    def test_empty_project_paths_returns_empty_string(self):
        entry = create_dataset_entry(project_paths=[])
        assert entry.extract_project_name() == ""


class TestProblemStatementDir:
    def test_problem_statement_dir_uses_instance_id(self, tmp_path):
        entry = create_dataset_entry(instance_id="microsoftInternal__NAV-123456")
        problem_dir = create_problem_statement_dir(tmp_path)

        with patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir / self.instance_id)):
            # Just test that the property is accessible and produces a path
            assert isinstance(entry.problem_statement_dir, Path)

    def test_problem_statement_dir_real_property(self):
        entry = create_dataset_entry(instance_id="microsoftInternal__NAV-123456")
        # Access the real property — it should return a Path with instance_id
        result = entry.problem_statement_dir
        assert isinstance(result, Path)
        assert "microsoftInternal__NAV-123456" in str(result)


class TestBaseAppPatchValidation:
    def test_non_baseapp_skips_validation(self):
        # Non-BaseApp entries should not validate layer
        entry = create_dataset_entry(project_paths=["App\\Apps\\W1\\Shopify\\app", "App\\Apps\\W1\\Shopify\\test"])
        # Should not raise
        assert entry is not None

    def test_baseapp_w1_patch_is_valid(self):
        patch_w1 = "diff --git a/App/Layers/W1/BaseApp/file.al b/App/Layers/W1/BaseApp/file.al\n+fix"
        test_patch_w1 = "diff --git a/App/Layers/W1/BaseApp/test.al b/App/Layers/W1/BaseApp/test.al\n+test"
        entry = create_dataset_entry(
            project_paths=["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\ERM"],
            patch=patch_w1,
            test_patch=test_patch_w1,
        )
        assert entry is not None

    def test_baseapp_non_w1_patch_raises(self):
        patch_non_w1 = "diff --git a/App/Layers/NA/BaseApp/file.al b/App/Layers/NA/BaseApp/file.al\n+fix"
        with pytest.raises(ValueError, match="non-W1 layer"):
            create_dataset_entry(
                project_paths=["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\ERM"],
                patch=patch_non_w1,
                test_patch=VALID_TEST_PATCH,
            )
