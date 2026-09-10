"""Tests for project categorization operations."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bcbench.exceptions import ProjectDiscoveryError
from bcbench.operations.project_operations import (
    _canonical_project_path,
    _is_test_project,
    categorize_projects,
    find_project_path,
    is_test_project,
    order_project_paths,
)


def _create_project(repo_path: Path, relative_path: str) -> Path:
    project_path = repo_path / relative_path
    project_path.mkdir(parents=True)
    (project_path / "app.json").write_text("{}", encoding="utf-8")
    return project_path


class TestIsTestProject:
    """Test suite for _is_test_project helper function."""

    def test_is_test_project_with_test_identifier(self):
        assert _is_test_project("src/test", ("test", "tests")) is True

    def test_is_test_project_with_tests_identifier(self):
        assert _is_test_project("src/tests", ("test", "tests")) is True

    def test_is_test_project_with_windows_separator(self):
        assert _is_test_project("src\\test", ("test", "tests")) is True

    def test_is_test_project_case_insensitive(self):
        assert _is_test_project("src/Test", ("test", "tests")) is True

    def test_is_test_project_casefolds_configured_identifiers(self):
        assert _is_test_project("src/QUALITY", ("Quality",)) is True

    def test_is_test_project_substring_not_path_component(self):
        assert _is_test_project("src/contest", ("test", "tests")) is False

    def test_is_test_project_without_identifier(self):
        assert _is_test_project("src/app", ("test", "tests")) is False

    def test_is_test_project_uses_configured_identifiers(self):
        assert is_test_project("src/tests") is True
        assert is_test_project("src/app") is False


class TestCategorizeProjects:
    """Test suite for categorize_projects function."""

    def test_categorize_projects_with_standard_test_folder(self):
        project_paths = ["src/app", "src/test", "src/lib"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert test_projects == ["src/test"]
        assert sorted(app_projects) == ["src/app", "src/lib"]

    def test_categorize_projects_with_tests_folder(self):
        project_paths = ["app/main", "app/tests", "app/utils"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert test_projects == ["app/tests"]
        assert sorted(app_projects) == ["app/main", "app/utils"]

    def test_categorize_projects_with_windows_path_separator(self):
        project_paths = ["app\\main", "app\\test", "app\\utils"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert test_projects == ["app\\test"]
        assert sorted(app_projects) == ["app\\main", "app\\utils"]

    def test_categorize_projects_with_mixed_separators(self):
        project_paths = ["app/main", "app\\tests", "app/utils"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert test_projects == ["app\\tests"]
        assert sorted(app_projects) == ["app/main", "app/utils"]

    def test_categorize_projects_case_insensitive(self):
        project_paths = ["src/App", "src/Test", "src/TESTS"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert sorted(test_projects) == ["src/TESTS", "src/Test"]
        assert app_projects == ["src/App"]

    def test_categorize_projects_multiple_test_projects(self):
        project_paths = ["src/app1", "src/test1", "src/app2", "src/tests"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert sorted(test_projects) == ["src/test1", "src/tests"]
        assert sorted(app_projects) == ["src/app1", "src/app2"]

    def test_categorize_projects_fails_without_test_projects(self):
        project_paths = ["src/app1", "src/app2", "src/lib"]
        with pytest.raises(RuntimeError, match="Project categorization failed"):
            categorize_projects(project_paths)

    def test_categorize_projects_fails_without_app_projects(self):
        project_paths = ["src/test", "src/tests"]
        with pytest.raises(RuntimeError, match="Project categorization failed"):
            categorize_projects(project_paths)

    def test_categorize_projects_with_test_substring_in_app_project(self):
        """Verify projects with 'test' as substring in the name (not as a path component) are categorized as app projects."""
        project_paths = ["src/latest-app", "src/contest", "src/test"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert test_projects == ["src/test"]
        assert sorted(app_projects) == ["src/contest", "src/latest-app"]

    def test_categorize_projects_nested_test_path(self):
        project_paths = ["src/app", "src/modules/test", "src/lib"]
        test_projects, app_projects = categorize_projects(project_paths)

        assert test_projects == ["src/modules/test"]
        assert sorted(app_projects) == ["src/app", "src/lib"]

    def test_categorize_projects_empty_list(self):
        """Test that empty project list raises RuntimeError."""
        project_paths = []
        with pytest.raises(RuntimeError, match="Project categorization failed"):
            categorize_projects(project_paths)


class TestFindProjectPath:
    def test_find_project_path_uses_nearest_app_json(self, tmp_path):
        repo_path = tmp_path / "repo"
        project_path = _create_project(repo_path, "App/Layers/W1/Tests/SCM-Manufacturing")
        test_file = project_path / "ProductionOrder.Codeunit.al"
        test_file.write_text("codeunit 137310 Tests {}", encoding="utf-8")

        result = find_project_path(repo_path, "App/Layers/W1/Tests/SCM-Manufacturing/ProductionOrder.Codeunit.al")

        assert result == str(project_path.relative_to(repo_path))

    def test_find_project_path_prefers_nested_bcapps_test_project(self, tmp_path):
        repo_path = tmp_path / "repo"
        _create_project(repo_path, "src/MyApp")
        test_project = _create_project(repo_path, "src/MyApp/test")
        test_file = test_project / "Regression.Codeunit.al"
        test_file.write_text("codeunit 50100 Tests {}", encoding="utf-8")

        result = find_project_path(repo_path, "src/MyApp/test/Regression.Codeunit.al")

        assert result == str(test_project.relative_to(repo_path))

    def test_find_project_path_rejects_file_without_app_json(self, tmp_path):
        repo_path = tmp_path / "repo"
        source_file = repo_path / "App/Unknown/Thing.al"
        source_file.parent.mkdir(parents=True)
        source_file.write_text("table 50100 Thing {}", encoding="utf-8")

        with pytest.raises(ProjectDiscoveryError, match=r"No owning app\.json.*App/Unknown/Thing\.al"):
            find_project_path(repo_path, "App/Unknown/Thing.al")

    def test_find_project_path_rejects_repository_escape(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with pytest.raises(ProjectDiscoveryError, match="outside repository"):
            find_project_path(repo_path, "../outside.al")


class TestOrderProjectPaths:
    def test_canonical_project_path_normalizes_separators_trailing_slash_and_case(self):
        assert _canonical_project_path("App\\Layers\\W1\\BaseApp\\") == _canonical_project_path("app/layers/w1/baseapp")

    def test_order_project_paths_prefers_dataset_order_then_sorts_new_paths(self):
        declared = ["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\SCM"]
        discovered = [
            "App/Layers/W1/Tests/SCM-Manufacturing",
            "App/Layers/W1/BaseApp",
            "App/Layers/W1/Tests/Assembly",
        ]

        assert order_project_paths(declared, discovered) == [
            "App/Layers/W1/BaseApp",
            "App/Layers/W1/Tests/Assembly",
            "App/Layers/W1/Tests/SCM-Manufacturing",
        ]

    def test_order_project_paths_matches_canonically_and_returns_duplicates_once(self):
        declared = ["APP\\MAIN\\"]
        discovered = ["app/main", "APP\\MAIN\\", "app/zeta", "App/Alpha"]

        assert order_project_paths(declared, discovered) == ["app/main", "App/Alpha", "app/zeta"]

    def test_order_project_paths_is_deterministic_for_unordered_canonical_duplicates(self):
        script = """
from bcbench.operations.project_operations import order_project_paths

print(order_project_paths(
    ["APP\\\\MAIN\\\\"],
    {"app/main", "APP\\\\MAIN\\\\", "app/zeta", "App/Alpha"},
))
"""
        outputs = {
            subprocess.check_output(
                [sys.executable, "-c", script],
                env={**os.environ, "PYTHONHASHSEED": seed},
                text=True,
            ).strip()
            for seed in ("1", "3")
        }

        assert outputs == {"['app/main', 'App/Alpha', 'app/zeta']"}


def test_operations_exports_project_discovery_functions():
    from bcbench import operations

    assert operations.find_project_path is find_project_path
    assert operations.is_test_project is is_test_project
    assert operations.order_project_paths is order_project_paths
