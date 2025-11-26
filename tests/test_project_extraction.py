"""Test project name extraction from project paths."""

import pytest

from tests.conftest import create_dataset_entry


class TestProjectExtraction:
    @pytest.mark.parametrize(
        "project_paths,expected_project",
        [
            (["App\\Apps\\W1\\Sustainability\\app", "App\\Apps\\W1\\Sustainability\\test"], "Sustainability"),
            (["App\\Apps\\W1\\Sustainability\\test", "App\\Apps\\W1\\Sustainability\\app"], "Sustainability"),
            (["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\BaseAppTest"], "BaseApp"),
            (["App\\Apps\\W1\\Shopify\\app", "App\\Apps\\W1\\Shopify\\test"], "Shopify"),
            (["App\\Apps\\W1\\Shopify\\test", "App\\Apps\\W1\\Shopify\\app"], "Shopify"),
            (["App\\Apps\\W1\\EssentialBusinessHeadlines\\app", "App\\Apps\\W1\\EssentialBusinessHeadlines\\test"], "EssentialBusinessHeadlines"),
            (["App\\Layers\\W1\\Tests\\SCM-Manufacturing", "App\\Layers\\W1\\Tests\\SCM"], "SCM-Manufacturing"),
            (["App\\Layers\\W1\\Tests\\SCM", "App\\Layers\\W1\\Tests\\SCM-Manufacturing"], "SCM"),
            (["src/app", "src/test"], "app"),
            (["src/test", "src/app"], "test"),
            (["src", "src/other"], "src"),
        ],
    )
    def test_extract_project_name_from_various_paths(self, project_paths, expected_project):
        entry = create_dataset_entry(project_paths=project_paths)

        assert entry.extract_project_name() == expected_project

    def test_extract_project_name_from_multiple_paths_uses_first(self):
        entry = create_dataset_entry(project_paths=["App\\Apps\\W1\\Sustainability\\app", "App\\Apps\\W1\\Sustainability\\test"])

        assert entry.extract_project_name() == "Sustainability"

    def test_extract_project_name_handles_forward_slashes(self):
        entry = create_dataset_entry(project_paths=["App/Apps/W1/Sustainability/app", "App/Apps/W1/Sustainability/test"])

        assert entry.extract_project_name() == "Sustainability"
