from bcbench.results.completeness import EvaluationCompleteness


def test_completeness_counts_unique_missing_and_duplicate_results():
    completeness = EvaluationCompleteness.from_instance_ids(4, ["a", "b", "b"])

    assert completeness.expected_entry_count == 4
    assert completeness.produced_entry_count == 2
    assert completeness.missing_entry_count == 2
    assert completeness.duplicate_result_count == 1
    assert completeness.complete is False


def test_completeness_metadata_is_explicit_for_external_storage():
    completeness = EvaluationCompleteness.from_instance_ids(2, ["a", "b"])

    assert completeness.to_metadata() == {
        "expected_entry_count": 2,
        "produced_entry_count": 2,
        "missing_entry_count": 0,
        "unexpected_entry_count": 0,
        "duplicate_result_count": 0,
        "evaluation_complete": True,
    }
