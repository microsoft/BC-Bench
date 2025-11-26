from bcbench.dataset import DatasetEntry
from bcbench.evaluate import create_pipeline
from bcbench.results.result_writer import get_info_from_dataset_entry
from bcbench.types import EvaluationCategory


def test_all_categories_have_pipelines():
    for category in EvaluationCategory:
        pipeline = create_pipeline(category)
        assert pipeline is not None


def test_all_categories_handled_in_get_info_from_dataset_entry(sample_dataset_entry_with_problem_statement: DatasetEntry):
    for category in EvaluationCategory:
        input_text, expected_output = get_info_from_dataset_entry(sample_dataset_entry_with_problem_statement, category)
        assert isinstance(input_text, str)
        assert isinstance(expected_output, str)
        assert len(expected_output) > 0
