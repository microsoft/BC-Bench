from pathlib import Path

from bcbench.dataset import BugFixEntry, CodeReviewEntry, HelloWorldEntry, NL2ALEntry
from bcbench.dataset.codereview import ReviewComment, Severity
from bcbench.types import AgentType, EvaluationCategory


def test_all_agent_types_have_target_dir():
    repo_path = Path("C:/test/repo")
    for agent_type in AgentType:
        target_dir = agent_type.get_target_dir(repo_path)
        assert isinstance(target_dir, Path)
        assert str(target_dir).startswith(str(repo_path))


def test_all_agent_types_have_instruction_filename():
    for agent_type in AgentType:
        filename = agent_type.instruction_filename
        assert isinstance(filename, str)
        assert filename.endswith(".md")


def test_all_categories_have_pipelines():
    for category in EvaluationCategory:
        pipeline = category.pipeline
        assert pipeline is not None


def test_all_categories_have_entry_classes():
    for category in EvaluationCategory:
        entry_cls = category.entry_class
        assert entry_cls is not None


def test_all_categories_have_aggregate_classes():
    from bcbench.results.leaderboard import LeaderboardAggregate

    for category in EvaluationCategory:
        aggregate_cls = category.aggregate_class
        assert issubclass(aggregate_cls, LeaderboardAggregate)


def test_all_categories_handled_in_get_expected_output(sample_dataset_entry_with_problem_statement: BugFixEntry, sample_nl2al_entry: NL2ALEntry, sample_hello_world_entry: HelloWorldEntry):
    for category in EvaluationCategory:
        entry_cls = category.entry_class
        if entry_cls == CodeReviewEntry:
            # CodeReviewEntry has a different schema — test separately
            entry = CodeReviewEntry(
                instance_id=sample_dataset_entry_with_problem_statement.instance_id,
                repo=sample_dataset_entry_with_problem_statement.repo,
                base_commit=sample_dataset_entry_with_problem_statement.base_commit,
                created_at=sample_dataset_entry_with_problem_statement.created_at,
                environment_setup_version=sample_dataset_entry_with_problem_statement.environment_setup_version,
                patch=sample_dataset_entry_with_problem_statement.patch,
                expected_comments=[ReviewComment(file="test.al", line_start=1, body="Test comment", severity=Severity.MEDIUM)],
            )
        elif entry_cls is NL2ALEntry:
            entry = sample_nl2al_entry
        elif entry_cls is HelloWorldEntry:
            entry = sample_hello_world_entry
        else:
            # Reconstruct entry as the category-specific type so get_expected_output() works
            entry = entry_cls.model_validate(sample_dataset_entry_with_problem_statement.model_dump(by_alias=True))

        input_text = entry.get_task()
        expected_output = entry.get_expected_output()
        assert isinstance(input_text, str)
        assert len(input_text) > 0
        # ExpectedOutput is `str | Checklist`: string for execution-based categories,
        # `{"assertions": [...]}` for lm_checklist-driven ones.
        if isinstance(expected_output, dict):
            assert "assertions" in expected_output
        else:
            assert isinstance(expected_output, str)
            assert expected_output


def test_all_categories_have_evaluators():
    for category in EvaluationCategory:
        evaluators = category.evaluators
        assert isinstance(evaluators, list)
        assert evaluators, f"{category} must declare at least one evaluator"
        assert all(isinstance(e, str) and e for e in evaluators)


def test_all_categories_have_core_score():
    for category in EvaluationCategory:
        assert isinstance(category.core_score, str)
        assert category.core_score, f"{category} must declare a non-empty core_score"
