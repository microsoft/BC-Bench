"""Tests for dataset entry hierarchy and factory pattern."""

import json

import pytest

from bcbench.dataset import BaseDatasetEntry, BugFixDatasetEntry, TestGenerationDatasetEntry, create_entry_from_json
from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


class TestDatasetEntryHierarchy:
    def test_dataset_entry_inherits_from_base(self):
        assert issubclass(DatasetEntry, BaseDatasetEntry)

    def test_bugfix_entry_inherits_from_dataset_entry(self):
        assert issubclass(BugFixDatasetEntry, DatasetEntry)
        assert issubclass(BugFixDatasetEntry, BaseDatasetEntry)

    def test_testgeneration_entry_inherits_from_dataset_entry(self):
        assert issubclass(TestGenerationDatasetEntry, DatasetEntry)
        assert issubclass(TestGenerationDatasetEntry, BaseDatasetEntry)

    def test_dataset_entry_instance_is_base(self):
        entry = create_dataset_entry()
        assert isinstance(entry, BaseDatasetEntry)

    def test_base_entry_has_common_fields(self):
        entry = create_dataset_entry()
        assert hasattr(entry, "repo")
        assert hasattr(entry, "instance_id")
        assert hasattr(entry, "base_commit")
        assert hasattr(entry, "created_at")
        assert hasattr(entry, "environment_setup_version")
        assert hasattr(entry, "project_paths")
        assert hasattr(entry, "metadata")

    def test_dataset_entry_has_category_specific_fields(self):
        entry = create_dataset_entry()
        assert hasattr(entry, "fail_to_pass")
        assert hasattr(entry, "pass_to_pass")
        assert hasattr(entry, "test_patch")
        assert hasattr(entry, "patch")

    def test_base_entry_common_methods(self):
        entry = create_dataset_entry()
        assert entry.extract_project_name() == "Shopify"
        assert entry.problem_statement_dir is not None


class TestCreateEntryFromJson:
    @pytest.fixture
    def sample_payload(self) -> dict:
        entry = create_dataset_entry()
        return json.loads(entry.model_dump_json(by_alias=True))

    def test_bugfix_category_creates_bugfix_entry(self, sample_payload):
        entry = create_entry_from_json(sample_payload, EvaluationCategory.BUG_FIX)
        assert isinstance(entry, BugFixDatasetEntry)
        assert isinstance(entry, DatasetEntry)
        assert isinstance(entry, BaseDatasetEntry)

    def test_testgeneration_category_creates_testgeneration_entry(self, sample_payload):
        entry = create_entry_from_json(sample_payload, EvaluationCategory.TEST_GENERATION)
        assert isinstance(entry, TestGenerationDatasetEntry)
        assert isinstance(entry, DatasetEntry)
        assert isinstance(entry, BaseDatasetEntry)

    def test_factory_accepts_json_string(self, sample_payload):
        json_str = json.dumps(sample_payload)
        entry = create_entry_from_json(json_str, EvaluationCategory.BUG_FIX)
        assert isinstance(entry, BugFixDatasetEntry)

    def test_factory_preserves_field_values(self, sample_payload):
        entry = create_entry_from_json(sample_payload, EvaluationCategory.BUG_FIX)
        assert entry.instance_id == sample_payload["instance_id"]
        assert entry.repo == sample_payload["repo"]
        assert entry.base_commit == sample_payload["base_commit"]

    def test_all_categories_handled_in_factory(self, sample_payload):
        for category in EvaluationCategory:
            entry = create_entry_from_json(sample_payload, category)
            assert entry is not None
            assert isinstance(entry, BaseDatasetEntry)


class TestDatasetLoaderWithCategory:
    def test_load_without_category_returns_dataset_entry(self, sample_dataset_file):
        from bcbench.dataset import load_dataset_entries

        entries = load_dataset_entries(sample_dataset_file)
        assert len(entries) > 0
        assert isinstance(entries[0], DatasetEntry)

    def test_load_with_bugfix_category_returns_bugfix_entry(self, sample_dataset_file):
        from bcbench.dataset import load_dataset_entries

        entries = load_dataset_entries(sample_dataset_file, category=EvaluationCategory.BUG_FIX)
        assert len(entries) > 0
        assert isinstance(entries[0], BugFixDatasetEntry)

    def test_load_with_testgeneration_category_returns_testgeneration_entry(self, sample_dataset_file):
        from bcbench.dataset import load_dataset_entries

        entries = load_dataset_entries(sample_dataset_file, category=EvaluationCategory.TEST_GENERATION)
        assert len(entries) > 0
        assert isinstance(entries[0], TestGenerationDatasetEntry)
