import pytest
from pydantic import ValidationError

from bcbench_core import dataset


@pytest.mark.parametrize("fields", [{"codeunitID": 0, "functionName": ["TestA"]}, {"codeunitID": 1, "functionName": []}])
def test_test_entry_rejects_invalid_selection(fields):
    with pytest.raises(ValidationError):
        dataset.TestEntry.model_validate(fields)


def test_test_entry_reads_dataset_json():
    entry = dataset.TestEntry.model_validate({"codeunitID": 137404, "functionName": ["TestB", "TestA"]})

    assert entry.functionName == frozenset({"TestA", "TestB"})
    assert entry.model_dump_json() == '{"codeunitID":137404,"functionName":["TestA","TestB"]}'
