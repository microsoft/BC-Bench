from bcbench.dataset import DatasetEntry, create_entry_from_json
from bcbench.evaluate import create_pipeline
from bcbench.results.bceval_export import get_info_from_dataset_entry
from bcbench.types import EvaluationCategory
from tests.conftest import create_dataset_entry


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


def test_all_categories_handled_in_dataset_entry_factory():
    entry = create_dataset_entry()
    payload = entry.model_dump(by_alias=True, mode="json")
    for category in EvaluationCategory:
        result = create_entry_from_json(payload, category)
        assert result is not None
