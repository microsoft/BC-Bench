"""Tests for project categorization operations."""

import pytest

from bcbench.operations.project_operations import categorize_projects


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
        """Test that projects with 'test' as substring but not in path are not categorized as test projects."""
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
