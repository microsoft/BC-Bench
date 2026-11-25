import re
from pathlib import Path

import pytest
from bcbench_core.agent.customization import CustomAgentsConfig, ToggleConfig, setup_custom_agent, setup_instructions

from bcbench.dataset import BugFixEntry
from bcbench.dataset.extensibility_request import ExtRequestTriageEntry
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


@pytest.mark.parametrize("repo", ["microsoftInternal/NAV", "microsoft/BCApps"])
def test_triage_entries_install_shared_agent_and_referenced_files(repo: str, tmp_path: Path):
    entry = ExtRequestTriageEntry.model_construct(repo=repo)
    profile_dir = instructions_profile_dir(entry.customization_profile)
    target_dir = tmp_path / ".github"
    setup_instructions(ToggleConfig(enabled=True), profile_dir, target_dir, "copilot-instructions.md")
    agent_name = setup_custom_agent(
        CustomAgentsConfig(enabled=True, name="extensibility-request-triage"),
        profile_dir,
        target_dir,
    )

    agent_text = (target_dir / "agents" / f"{agent_name}.agent.md").read_text(encoding="utf-8")
    referenced_files = re.findall(r"TRIAGE_ROOT/([\w/-]+\.(?:md|yaml))", agent_text)
    assert referenced_files
    for relative_path in referenced_files:
        assert (target_dir / "instructions" / "extensibility-request-triage" / relative_path).is_file()
