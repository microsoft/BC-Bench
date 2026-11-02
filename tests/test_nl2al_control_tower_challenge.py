import json
import re

import pytest

from bcbench.dataset import NL2ALEntry, load_evaluation_cohort
from bcbench.results.base import JudgeBasedEvaluationResult
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, BCalScenarioFailure, DatasetTier, EvaluationCategory
from tests.conftest import create_evaluation_context

CONTROL_TOWER_ID = "nl2al__collected-sales-operations-control-tower-1"
CONTROL_TOWER_PROMPT = (
    "Build a Sales & Operations Control Tower that continuously evaluates whether customer demand can be fulfilled profitably and on time. "
    "The solution should recommend actions, simulate alternatives, analyze the impact of decisions across all open demand and supply documents, "
    "prioritize customer commitments based on business rules, and provide planners with AI-assisted recommendations to optimize service level, "
    "profitability and working capital simultaneously."
)

# Each requirement must be covered by at least one critical assertion containing all listed terms.
CRITICAL_REQUIREMENTS = {
    "genuine terminal completion": ["safety", "discussion-only", "blocker", "completion review"],
    "compiles after last mutation": ["compiles", "last source mutation"],
    "real demand-vs-supply netting": ["open sales demand", "inventory", "supply document", "heuristic"],
    "cross-demand allocation": ["allocated", "competing open demand"],
    "configurable prioritization rules": ["business rules", "setup or rules table"],
    "scenario simulation": ["simulate", "recalculates", "without modifying"],
    "three impact dimensions": ["service level", "profitability", "margin", "working capital"],
    "planner-facing recommendations": ["recommended actions", "page"],
    "no manufactured progress": ["health-check", "utility objects", "does not claim"],
}


@pytest.fixture(scope="module")
def challenge_path():
    return EvaluationCategory.NL2AL.dataset_path(DatasetTier.CHALLENGE)


@pytest.fixture(scope="module")
def control_tower(challenge_path) -> NL2ALEntry:
    matches = [entry for entry in NL2ALEntry.load(challenge_path) if entry.instance_id == CONTROL_TOWER_ID]
    assert len(matches) == 1
    return matches[0]


def test_control_tower_uses_original_prompt_without_hidden_constraints(control_tower):
    assert control_tower.nl_prompt == CONTROL_TOWER_PROMPT
    assert control_tower.get_task() == CONTROL_TOWER_PROMPT
    assert control_tower.metadata.family == "sales-operations-control-tower"


@pytest.mark.parametrize(("requirement", "terms"), CRITICAL_REQUIREMENTS.items())
def test_control_tower_has_critical_assertion_for_requirement(control_tower, requirement, terms):
    critical = [assertion["text"].lower() for assertion in control_tower.expected if assertion["level"] == "critical"]

    assert any(all(term in text for term in terms) for text in critical), requirement


def test_control_tower_assertions_do_not_depend_on_object_or_file_names(control_tower):
    texts = [assertion["text"] for assertion in control_tower.expected]

    assert not any(re.search(r"control\s*tower|\.al\b|\b(table|page|codeunit)\s+\d+", text, re.IGNORECASE) for text in texts)
    assert len(set(texts)) == len(texts)


def test_control_tower_cohort_selects_only_the_new_challenge(challenge_path):
    path = challenge_path.parent / "cohorts" / "sales-operations-control-tower.json"

    resolved = load_evaluation_cohort(path, tier=DatasetTier.CHALLENGE, available_entries=NL2ALEntry.load(challenge_path))

    assert resolved.cohort.entries == [CONTROL_TOWER_ID]


def _export(control_tower, challenge_path, tmp_path, *, evidence, failure=None, error_message=None):
    context = create_evaluation_context(tmp_path, entry=control_tower, category=EvaluationCategory.NL2AL, agent_name=AgentHarness.BCAL)
    context.tier = DatasetTier.CHALLENGE
    context.evidence = evidence
    context.bcal_failure = failure
    output = "diff --git a/Planner.al b/Planner.al"
    result = JudgeBasedEvaluationResult.create_failure(context, output, error_message) if error_message else JudgeBasedEvaluationResult.create_raw(context, output)

    write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.NL2AL)
    return json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))


def test_completed_scenario_evidence_reaches_judge_without_terminal_failure(control_tower, challenge_path, tmp_path):
    evidence = {"contractVersion": "1.0", "trace": {"events": [{"type": "compile", "success": True}]}}

    row = _export(control_tower, challenge_path, tmp_path, evidence=evidence)

    assert row["input"] == CONTROL_TOWER_PROMPT
    assert row["expected"]["assertions"] == control_tower.expected
    assert row["context"] == evidence
    assert row["metadata"]["bcal_failure_code"] is None
    assert row["metadata"]["bcal_terminal_reason"] is None
    assert row["metadata"]["error_message"] is None


def test_safety_limit_interruption_is_exported_as_incomplete_failure(control_tower, challenge_path, tmp_path):
    evidence = {"contractVersion": "1.0", "trace": {"events": [{"type": "terminal", "reason": "absolute_turn_safety_limit"}]}}
    failure = BCalScenarioFailure(code="incomplete_execution", message="interrupted_before_finalization", stepId="benchmark-prompt", retryable=False)

    row = _export(control_tower, challenge_path, tmp_path, evidence=evidence, failure=failure, error_message="BCal scenario exited with status 1")

    assert row["expected"]["assertions"] == control_tower.expected
    assert row["context"] == evidence
    assert row["metadata"]["bcal_failure_code"] == "incomplete_execution"
    assert row["metadata"]["bcal_terminal_reason"] == "interrupted_before_finalization"
    assert row["metadata"]["error_message"] == "BCal scenario exited with status 1"
