from bcbench.exceptions import _extract_test_errors

SAMPLE_TEST_OUTPUT = """\
BcContainerHelper version 6.1.11-preview1992978
BC.HelperFunctions emits usage statistics telemetry to Microsoft
Running on Windows, PowerShell 7.5.4
::group::Running Tests for: 148181, expectation: Pass
[37m[13:33:33] Running tests for Codeunit 148181 with functions: TestCustomAmountIsPositiveForNegativeTotalOfGL[0m
Using Container
WARNING: TaskScheduler is running in the container, this can lead to test failures. Specify -EnableTaskScheduler:$false to disable Task Scheduler.
Connecting to http://localhost:80/BC/cs?tenant=default
Setting test codeunit range '148181'
Codeunit 148181 Sustainability Journal Test
    Testfunction TestCustomAmountIsPositiveForNegativeTotalOfGL Failure (4.64 seconds)
      Error:
        Assert.AreEqual failed. Expected:<248.67> (Decimal). Actual:<-248.67> (Decimal). The custom amount must be positive.
      Call Stack:
        Assert(CodeUnit 130000).AreEqual line 3 - Tests-TestLibraries by Microsoft
        "Sustainability Journal Test"(CodeUnit 148181).TestCustomAmountIsPositiveForNegativeTotalOfGL line 31 - Sustainability Tests by Microsoft
        "Test Runner - Mgt"(CodeUnit 130454).RunTests line 21 - Test Runner by Microsoft
        "Test Runner - Isol. Codeunit"(CodeUnit 130450).OnRun(Trigger) line 4 - Test Runner by Microsoft
        "Test Suite Mgt."(CodeUnit 130456).RunTests line 2 - Test Runner by Microsoft
        "Test Suite Mgt."(CodeUnit 130456).RunSelectedTests line 35 - Test Runner by Microsoft
        "Command Line Test Tool"(Page 130455)."RunSelectedTests - OnAction"(Trigger) line 7 - Test Runner by Microsoft
[31m[13:33:54] Tests failed for Codeunit 148181[0m
::error title=BCBench::Tests failed for Codeunit 148181
"""


class TestExtractTestErrors:
    def test_extracts_codeunit_line(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Codeunit 148181 Sustainability Journal Test" in result
        print(result)

    def test_extracts_testfunction_failure(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Testfunction TestCustomAmountIsPositiveForNegativeTotalOfGL Failure" in result

    def test_extracts_error_message(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Assert.AreEqual failed" in result
        assert "The custom amount must be positive" in result

    def test_extracts_call_stack(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Assert(CodeUnit 130000).AreEqual line 3" in result

    def test_excludes_bccontainerhelper_version(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "BcContainerHelper version" not in result

    def test_excludes_telemetry_message(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "BC.HelperFunctions emits" not in result

    def test_excludes_running_on_windows(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Running on Windows" not in result

    def test_excludes_using_container(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Using Container" not in result

    def test_excludes_task_scheduler_warning(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "TaskScheduler" not in result

    def test_excludes_connecting_to_url(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "Connecting to http://" not in result

    def test_excludes_github_group_commands(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT)
        assert "::group::" not in result
        assert "::error" not in result

    def test_returns_empty_string_for_empty_input(self):
        assert _extract_test_errors("") == ""

    def test_respects_max_lines(self):
        result = _extract_test_errors(SAMPLE_TEST_OUTPUT, max_lines=3)
        lines = result.splitlines()
        assert len(lines) == 3


class TestTestExecutionErrorMessage:
    def test_error_message_is_concise(self):
        from bcbench.exceptions import TestExecutionError

        error = TestExecutionError("Pass", stderr="", stdout=SAMPLE_TEST_OUTPUT)
        message = str(error)

        # Should include the expectation
        assert "expected: Pass" in message

        # Should include the key error info
        assert "Assert.AreEqual failed" in message

        # Should NOT include verbose BCContainerHelper output
        assert "BcContainerHelper version" not in message
        assert "Using Container" not in message
        assert "TaskScheduler" not in message
