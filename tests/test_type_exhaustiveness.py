from pathlib import Path

from bcbench.dataset import BugFixTestGenEntry
from bcbench.evaluate import create_pipeline
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
        pipeline = create_pipeline(category)
        assert pipeline is not None


def test_all_categories_handled_in_get_expected_output(sample_dataset_entry_with_problem_statement: BugFixTestGenEntry):
    for category in EvaluationCategory:
        input_text = sample_dataset_entry_with_problem_statement.get_task()
        expected_output = sample_dataset_entry_with_problem_statement.get_expected_output(category)
        assert isinstance(input_text, str)
        assert isinstance(expected_output, str)
        assert len(expected_output) > 0
