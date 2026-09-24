from copy import deepcopy

import pytest

from bcbench.agent.pr_review.definitions import (
    DEFAULT_PR_REVIEW_DEFINITION_ID,
    get_pr_review_definition,
    resolve_pr_review_definition,
    validate_requested_pr_review_definition,
)
from bcbench.agent.pr_review.run_manifest import RunManifest
from bcbench.exceptions import AgentError


def _baseline_manifest_payload() -> dict:
    return {
        "schema_version": 1,
        "status": "completed",
        "started_at": "2026-09-24T12:52:10Z",
        "completed_at": "2026-09-24T13:05:08Z",
        "failure_reason": None,
        "engine": {
            "repository": "microsoft/BC-ALAgents",
            "commit": "03239afe611a3eff490002eba0e4098b48099ba3",
            "agent_version": "0.1.0",
        },
        "bcquality": {
            "commit": "b74967bc5b7a454eae19d6a1250199afd869f064",
            "source_snapshot": "096dca9a79cc20bb42bfd0d42d317672f39270e03532c119ac7c47084323d903",
        },
        "configuration": {
            "copilot_cli_version": "1.0.83",
            "root_model": "gpt-5.6-sol",
            "leaf_model": "gpt-5.6-luna",
            "leaf_execution": "serial",
            "max_leaf_concurrency": 4,
            "cli_timeout_minutes": 30,
            "minimum_severity": "Medium",
            "agent_minimum_severity": "Medium",
            "review_source": "local",
        },
        "plan": {
            "skill_id": "al-code-review",
            "leaf_count": 1,
            "leaf_ids": ["al-security-review"],
        },
        "processes": [],
    }


def _baseline_manifest() -> RunManifest:
    return RunManifest.model_validate(_baseline_manifest_payload())


def test_canonical_pr_review_manifest_resolves_baseline_definition() -> None:
    definition = resolve_pr_review_definition(_baseline_manifest(), bcquality_repository="microsoft/BCQuality")

    assert definition is not None
    assert definition.id == DEFAULT_PR_REVIEW_DEFINITION_ID
    assert definition.display_name == "BC PR Review — Production / Sol / Luna / Serial v1"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["configuration"].update(leaf_model="gpt-5.6-sol"),
        lambda payload: payload["configuration"].update(leaf_execution="parallel"),
        lambda payload: payload["configuration"].update(max_leaf_concurrency=1),
        lambda payload: payload["engine"].update(commit="a" * 40),
        lambda payload: payload["configuration"].update(copilot_cli_version="1.0.84"),
        lambda payload: payload["bcquality"].update(commit="a" * 40),
        lambda payload: payload["bcquality"].update(source_snapshot="a" * 64),
        lambda payload: payload["configuration"].update(minimum_severity="High"),
    ],
    ids=["leaf-model", "schedule", "concurrency", "engine", "cli", "bcquality-commit", "bcquality-snapshot", "policy"],
)
def test_baseline_mismatches_are_unclassified(mutation) -> None:
    payload = deepcopy(_baseline_manifest_payload())
    mutation(payload)

    definition = resolve_pr_review_definition(RunManifest.model_validate(payload), bcquality_repository="microsoft/BCQuality")

    assert definition is None


def test_unknown_definition_cannot_create_an_arbitrary_display_name() -> None:
    with pytest.raises(AgentError, match="Unknown BC PR Review definition"):
        get_pr_review_definition("my-unreviewed-profile")


def test_requested_definition_rejects_mismatched_configured_inputs() -> None:
    with pytest.raises(AgentError, match="does not match configured inputs"):
        validate_requested_pr_review_definition(
            DEFAULT_PR_REVIEW_DEFINITION_ID,
            engine_commit="03239afe611a3eff490002eba0e4098b48099ba3",
            copilot_cli_version="1.0.83",
            root_model="gpt-5.6-sol",
            leaf_model="mai-code-1.1-flash",
            leaf_execution="serial",
            max_leaf_concurrency=4,
        )
