from unittest.mock import patch

import pytest
from bcbench_core.container import ContainerConfig
from bcbench_core.dataset import TestEntry
from bcbench_core.exceptions import TestExecutionError

from bcbench.operations import test_operations

_CONTAINER = ContainerConfig("bcserver", "admin", "secret", "CRONUS")
_FAIL_TO_PASS = [TestEntry(codeunitID=100, functionName=frozenset({"TestFix"}))]
_PASS_TO_PASS = [TestEntry(codeunitID=200, functionName=frozenset({"TestExisting"}))]


def test_both_suites_must_pass():
    with patch.object(test_operations, "run_test_suite") as run:
        test_operations.run_tests(_FAIL_TO_PASS, _PASS_TO_PASS, _CONTAINER)

    assert [call.args for call in run.call_args_list] == [(_FAIL_TO_PASS, "Pass", _CONTAINER), (_PASS_TO_PASS, "Pass", _CONTAINER)]


@pytest.mark.parametrize(
    ("fail_to_pass", "pass_to_pass"),
    [(_FAIL_TO_PASS, []), ([], _PASS_TO_PASS), ([], [])],
)
def test_skips_empty_suites(fail_to_pass, pass_to_pass):
    with patch.object(test_operations, "run_test_suite") as run:
        test_operations.run_tests(fail_to_pass, pass_to_pass, _CONTAINER)

    assert [call.args for call in run.call_args_list] == [(tests, "Pass", _CONTAINER) for tests in (fail_to_pass, pass_to_pass) if tests]


def test_empty_suites_are_logged(caplog):
    caplog.set_level("INFO", logger="bcbench.operations.test_operations")
    with patch.object(test_operations, "run_test_suite") as run:
        test_operations.run_tests([], [], _CONTAINER)

    run.assert_not_called()
    assert "No fail-to-pass tests to run" in caplog.text
    assert "No pass-to-pass tests to run" in caplog.text


def test_suite_failure_propagates_before_regression_tests():
    with patch.object(test_operations, "run_test_suite", side_effect=TestExecutionError("Pass")) as run, pytest.raises(TestExecutionError):
        test_operations.run_tests(_FAIL_TO_PASS, _PASS_TO_PASS, _CONTAINER)

    run.assert_called_once_with(_FAIL_TO_PASS, "Pass", _CONTAINER)
