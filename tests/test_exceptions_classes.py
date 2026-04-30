"""Tests for exception class constructors and attributes."""

from bcbench.exceptions import (
    AgentTimeoutError,
    BuildError,
    BuildTimeoutExpired,
    CollectionError,
    EntryNotFoundError,
    InvalidEntryFormatError,
    NoEntriesFoundError,
    NoTestsExtractedError,
    PatchApplicationError,
    TestExecutionTimeoutExpired,
    _extract_test_errors,
)
from bcbench.types import AgentMetrics


class TestEntryNotFoundError:
    def test_message_contains_entry_id(self):
        error = EntryNotFoundError("my-entry-123")
        assert "my-entry-123" in str(error)

    def test_entry_id_attribute(self):
        error = EntryNotFoundError("my-entry-123")
        assert error.entry_id == "my-entry-123"

    def test_is_dataset_error(self):
        from bcbench.exceptions import DatasetError

        error = EntryNotFoundError("x")
        assert isinstance(error, DatasetError)


class TestInvalidEntryFormatError:
    def test_message_contains_entry(self):
        error = InvalidEntryFormatError("bad-entry")
        assert "bad-entry" in str(error)

    def test_message_with_details(self):
        error = InvalidEntryFormatError("bad-entry", "missing field")
        assert "bad-entry" in str(error)
        assert "missing field" in str(error)

    def test_message_without_details(self):
        error = InvalidEntryFormatError("bad-entry")
        assert "bad-entry" in str(error)
        assert error.details == ""

    def test_entry_attribute(self):
        error = InvalidEntryFormatError("my-entry", "some detail")
        assert error.entry == "my-entry"
        assert error.details == "some detail"


class TestNoEntriesFoundError:
    def test_message_with_criteria(self):
        error = NoEntriesFoundError("instance_id=foo")
        assert "instance_id=foo" in str(error)

    def test_message_without_criteria(self):
        error = NoEntriesFoundError()
        assert "No entries matched" in str(error)
        assert error.criteria == ""

    def test_criteria_attribute(self):
        error = NoEntriesFoundError("my-filter")
        assert error.criteria == "my-filter"


class TestPatchApplicationError:
    def test_message_contains_patch_name(self):
        error = PatchApplicationError("test.patch")
        assert "test.patch" in str(error)

    def test_message_with_stderr(self):
        error = PatchApplicationError("test.patch", "patch failed to apply")
        assert "test.patch" in str(error)
        assert "patch failed to apply" in str(error)

    def test_attributes(self):
        error = PatchApplicationError("my.patch", "error detail")
        assert error.patch_name == "my.patch"
        assert error.stderr == "error detail"

    def test_message_without_stderr(self):
        error = PatchApplicationError("my.patch")
        assert error.stderr == ""


class TestBuildError:
    def test_message_contains_project_path(self):
        error = BuildError("App/Layers/W1/BaseApp")
        assert "App/Layers/W1/BaseApp" in str(error)

    def test_project_path_attribute(self):
        error = BuildError("App/MyProject")
        assert error.project_path == "App/MyProject"

    def test_output_attribute(self):
        error = BuildError("App/MyProject", "some build output")
        assert error.output == "some build output"

    def test_errors_extracted_from_output(self):
        output = "file.al(10,5): error AL0001: Something went wrong"
        error = BuildError("App/MyProject", output)
        assert "error AL0001" in error.errors

    def test_errors_empty_when_no_output(self):
        error = BuildError("App/MyProject")
        assert error.errors == ""


class TestBuildTimeoutExpired:
    def test_message_contains_project_and_timeout(self):
        error = BuildTimeoutExpired("App/BigProject", 3600)
        assert "App/BigProject" in str(error)
        assert "3600" in str(error)

    def test_attributes(self):
        error = BuildTimeoutExpired("App/MyProject", 7200)
        assert error.project_path == "App/MyProject"
        assert error.timeout == 7200


class TestTestExecutionTimeoutExpired:
    def test_message_contains_tests_and_timeout(self):
        error = TestExecutionTimeoutExpired("codeunit 50100", 1800)
        assert "codeunit 50100" in str(error)
        assert "1800" in str(error)

    def test_attributes(self):
        error = TestExecutionTimeoutExpired("test entries", 900)
        assert error.tests == "test entries"
        assert error.timeout == 900


class TestNoTestsExtractedError:
    def test_message(self):
        error = NoTestsExtractedError()
        assert "No tests extracted" in str(error)


class TestAgentTimeoutError:
    def test_message(self):
        error = AgentTimeoutError("Agent timed out after 60s")
        assert "Agent timed out after 60s" in str(error)

    def test_with_metrics(self):
        metrics = AgentMetrics(execution_time=60.0)
        error = AgentTimeoutError("timed out", metrics=metrics)
        assert error.metrics is metrics

    def test_with_none_metrics(self):
        error = AgentTimeoutError("timed out")
        assert error.metrics is None
        assert error.config is None

    def test_with_config(self):
        from bcbench.types import ExperimentConfiguration

        config = ExperimentConfiguration(custom_instructions=True)
        error = AgentTimeoutError("timed out", config=config)
        assert error.config is config


class TestCollectionError:
    def test_message_contains_original(self):
        error = CollectionError("no data found")
        assert "no data found" in str(error)

    def test_message_includes_wip_note(self):
        error = CollectionError("something broke")
        assert "WIP" in str(error) or "hardcoded" in str(error)


class TestExtractTestErrorsFallback:
    def test_fallback_returns_last_lines_when_all_filtered(self):
        # All lines match skip patterns — should fall back to last N lines
        all_filtered_output = "\n".join(
            [
                "BcContainerHelper version 6.1.11",
                "BC.HelperFunctions emits telemetry",
                "Running on Windows, PowerShell 7.5.4",
                "Using Container",
                "WARNING: TaskScheduler is running",
                "Connecting to http://localhost:80",
            ]
        )
        result = _extract_test_errors(all_filtered_output, max_lines=2)
        lines = result.splitlines()
        assert len(lines) == 2
        assert lines[-1] == "Connecting to http://localhost:80"
