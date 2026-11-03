from bcbench.dataset import BugFixEntry
from bcbench.operations import instructions_profile_dir
from bcbench.types import EvaluationCategory


def test_shipped_profile_exists():
    assert instructions_profile_dir("microsoftInternal-NAV").is_dir()


def test_repo_grounded_profile_is_derived_from_repo():
    test_cases = [
        ("microsoftInternal/NAV", "microsoftInternal-NAV"),
        ("org/repo", "org-repo"),
        ("user/my-repo", "user-my-repo"),
    ]

    for repo_name, expected_profile in test_cases:
        entry = BugFixEntry.model_construct(repo=repo_name)
        assert entry.customization_profile == expected_profile, f"Failed for {repo_name}"


def test_every_category_entry_class_names_a_customization_profile():
    for category in EvaluationCategory:
        entry = category.entry_class.model_construct(repo="microsoft/BCApps")
        assert entry.customization_profile, f"{category} has no customization profile"
