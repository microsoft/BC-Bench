"""Tests for counterfactual dataset entry loading and resolution."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.dataset import CounterfactualEntry
from bcbench.exceptions import EntryNotFoundError
from bcbench.types import EvaluationCategory
from tests.conftest import (
    VALID_BASE_COMMIT,
    VALID_CREATED_AT,
    VALID_ENVIRONMENT_VERSION,
    VALID_PATCH,
    VALID_PROJECT_PATHS,
    VALID_REPO,
    VALID_TEST_PATCH,
)

BASE_INSTANCE_ID = "microsoftInternal__NAV-123456"
CF_INSTANCE_ID = "microsoftInternal__NAV-123456__cf-1"


def _create_base_jsonl(path: Path) -> Path:
    base_entry = {
        "instance_id": BASE_INSTANCE_ID,
        "repo": VALID_REPO,
        "base_commit": VALID_BASE_COMMIT,
        "environment_setup_version": VALID_ENVIRONMENT_VERSION,
        "project_paths": VALID_PROJECT_PATHS,
        "patch": VALID_PATCH,
        "test_patch": VALID_TEST_PATCH,
        "created_at": VALID_CREATED_AT,
        "FAIL_TO_PASS": [{"codeunitID": 100, "functionName": ["TestFunction"]}],
        "PASS_TO_PASS": [],
    }
    file = path / "bcbench.jsonl"
    file.write_text(json.dumps(base_entry) + "\n", encoding="utf-8")
    return file


def _create_cf_jsonl(path: Path, instance_id: str = CF_INSTANCE_ID) -> Path:
    cf_entry = {
        "instance_id": instance_id,
        "base_instance_id": BASE_INSTANCE_ID,
        "variant_description": "Test variant",
        "failure_layer": None,
        "problem_statement_override": None,
        "FAIL_TO_PASS": [{"codeunitID": 100, "functionName": ["TestFunction"]}],
        "PASS_TO_PASS": [],
        "test_patch": VALID_TEST_PATCH,
        "patch": VALID_PATCH,
    }
    file = path / "counterfactual.jsonl"
    file.write_text(json.dumps(cf_entry) + "\n", encoding="utf-8")
    return file


class TestCounterfactualEntryLoading:
    def test_load_resolves_base_fields(self, tmp_path):
        _create_base_jsonl(tmp_path)
        cf_file = _create_cf_jsonl(tmp_path)

        with patch("bcbench.dataset.counterfactual_entry._config") as mock_config:
            mock_config.paths.dataset_dir = tmp_path
            mock_config.paths.bc_bench_root = tmp_path
            mock_config.paths.problem_statement_dir = tmp_path / "problemstatement"
            mock_config.file_patterns.instance_pattern = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$"
            mock_config.file_patterns.problem_statement_readme = "README.md"

            entries = CounterfactualEntry.load(cf_file)

        assert len(entries) == 1
        entry = entries[0]
        assert entry.instance_id == CF_INSTANCE_ID
        assert entry.base_instance_id == BASE_INSTANCE_ID
        assert entry.repo == VALID_REPO
        assert entry.base_commit == VALID_BASE_COMMIT
        assert entry.environment_setup_version == VALID_ENVIRONMENT_VERSION
        assert list(entry.project_paths) == VALID_PROJECT_PATHS

    def test_load_by_entry_id(self, tmp_path):
        _create_base_jsonl(tmp_path)
        cf_file = _create_cf_jsonl(tmp_path)

        with patch("bcbench.dataset.counterfactual_entry._config") as mock_config:
            mock_config.paths.dataset_dir = tmp_path
            mock_config.paths.bc_bench_root = tmp_path
            mock_config.paths.problem_statement_dir = tmp_path / "problemstatement"
            mock_config.file_patterns.instance_pattern = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$"
            mock_config.file_patterns.problem_statement_readme = "README.md"

            entries = CounterfactualEntry.load(cf_file, entry_id=CF_INSTANCE_ID)

        assert len(entries) == 1
        assert entries[0].instance_id == CF_INSTANCE_ID

    def test_load_missing_base_raises(self, tmp_path):
        cf_file = _create_cf_jsonl(tmp_path)
        empty_base = tmp_path / "bcbench.jsonl"
        empty_base.write_text("", encoding="utf-8")

        with patch("bcbench.dataset.counterfactual_entry._config") as mock_config:
            mock_config.paths.dataset_dir = tmp_path
            mock_config.paths.bc_bench_root = tmp_path
            mock_config.paths.problem_statement_dir = tmp_path / "problemstatement"
            mock_config.file_patterns.instance_pattern = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$"
            mock_config.file_patterns.problem_statement_readme = "README.md"

            with pytest.raises(ValueError, match="Base entry"):
                CounterfactualEntry.load(cf_file)

    def test_load_entry_not_found_raises(self, tmp_path):
        _create_base_jsonl(tmp_path)
        cf_file = _create_cf_jsonl(tmp_path)

        with patch("bcbench.dataset.counterfactual_entry._config") as mock_config:
            mock_config.paths.dataset_dir = tmp_path
            mock_config.paths.bc_bench_root = tmp_path
            mock_config.paths.problem_statement_dir = tmp_path / "problemstatement"
            mock_config.file_patterns.instance_pattern = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$"
            mock_config.file_patterns.problem_statement_readme = "README.md"

            with pytest.raises(EntryNotFoundError):
                CounterfactualEntry.load(cf_file, entry_id="nonexistent__NAV-999__cf-1")


class TestCounterfactualEntrySchema:
    def test_get_expected_output_returns_patch(self, tmp_path):
        _create_base_jsonl(tmp_path)
        cf_file = _create_cf_jsonl(tmp_path)

        with patch("bcbench.dataset.counterfactual_entry._config") as mock_config:
            mock_config.paths.dataset_dir = tmp_path
            mock_config.paths.bc_bench_root = tmp_path
            mock_config.paths.problem_statement_dir = tmp_path / "problemstatement"
            mock_config.file_patterns.instance_pattern = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$"
            mock_config.file_patterns.problem_statement_readme = "README.md"

            entry = CounterfactualEntry.load(cf_file)[0]

        assert entry.get_expected_output() == VALID_PATCH

    def test_problem_statement_override_used(self, tmp_path):
        _create_base_jsonl(tmp_path)

        cf_entry = {
            "instance_id": CF_INSTANCE_ID,
            "base_instance_id": BASE_INSTANCE_ID,
            "variant_description": "Test variant",
            "failure_layer": None,
            "problem_statement_override": "dataset/problemstatement/microsoftInternal__NAV-123456__cf-1",
            "FAIL_TO_PASS": [{"codeunitID": 100, "functionName": ["TestFunction"]}],
            "PASS_TO_PASS": [],
            "test_patch": VALID_TEST_PATCH,
            "patch": VALID_PATCH,
        }
        cf_file = tmp_path / "counterfactual.jsonl"
        cf_file.write_text(json.dumps(cf_entry) + "\n", encoding="utf-8")

        with patch("bcbench.dataset.counterfactual_entry._config") as mock_config:
            mock_config.paths.dataset_dir = tmp_path
            mock_config.paths.bc_bench_root = tmp_path
            mock_config.paths.problem_statement_dir = tmp_path / "problemstatement"
            mock_config.file_patterns.instance_pattern = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+$"
            mock_config.file_patterns.problem_statement_readme = "README.md"

            entry = CounterfactualEntry.load(cf_file)[0]

        assert "cf-1" in str(entry.problem_statement_dir)


class TestCounterfactualCategory:
    def test_category_properties(self):
        cat = EvaluationCategory.CF
        assert cat.value == "cf"
        assert cat.is_counterfactual
        assert cat.prompt_template_key == "counterfactual"
        assert cat.dataset_path.name == "counterfactual.jsonl"
        assert cat.entry_class is CounterfactualEntry
        assert cat.pipeline is not None
        assert cat.summary_class is not None
        assert cat.result_class is not None

    def test_non_cf_categories_are_not_counterfactual(self):
        assert not EvaluationCategory.BUG_FIX.is_counterfactual
        assert not EvaluationCategory.TEST_GENERATION.is_counterfactual

    def test_reuses_bugfix_pipeline(self):
        from bcbench.evaluate import BugFixPipeline

        pipeline = EvaluationCategory.CF.pipeline
        assert isinstance(pipeline, BugFixPipeline)
