"""Test project name extraction from project paths."""

import pytest

from bcbench.dataset import DatasetEntry


class TestProjectExtraction:
    @pytest.mark.parametrize(
        "project_paths,expected_project",
        [
            (["App\\Apps\\W1\\Sustainability\\app"], "Sustainability"),
            (["App\\Apps\\W1\\Sustainability\\test"], "Sustainability"),
            (["App\\Layers\\W1\\BaseApp"], "BaseApp"),
            (["App\\Apps\\W1\\Shopify\\app"], "Shopify"),
            (["App\\Apps\\W1\\Shopify\\test"], "Shopify"),
            (["App\\Apps\\W1\\EssentialBusinessHeadlines\\app"], "EssentialBusinessHeadlines"),
            (["App\\Layers\\W1\\Tests\\SCM-Manufacturing"], "SCM-Manufacturing"),
            (["App\\Layers\\W1\\Tests\\SCM"], "SCM"),
            (["src/app"], "app"),
            (["src/test"], "test"),
            (["src"], "src"),
            ([], ""),
        ],
    )
    def test_extract_project_name_from_various_paths(self, project_paths, expected_project):
        entry = DatasetEntry(
            instance_id="test__123",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="26.5",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["Test1"]}],
            pass_to_pass=[],
            project_paths=project_paths,
        )

        assert entry.extract_project_name() == expected_project

    def test_extract_project_name_from_multiple_paths_uses_first(self):
        entry = DatasetEntry(
            instance_id="test__123",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="26.5",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["Test1"]}],
            pass_to_pass=[],
            project_paths=["App\\Apps\\W1\\Sustainability\\app", "App\\Apps\\W1\\Sustainability\\test"],
        )

        assert entry.extract_project_name() == "Sustainability"

    def test_extract_project_name_handles_forward_slashes(self):
        entry = DatasetEntry(
            instance_id="test__123",
            repo="test/repo",
            base_commit="a" * 40,
            environment_setup_version="26.5",
            fail_to_pass=[{"codeunitID": 100, "functionName": ["Test1"]}],
            pass_to_pass=[],
            project_paths=["App/Apps/W1/Sustainability/app"],
        )

        assert entry.extract_project_name() == "Sustainability"
