"""Tests for logging setup, sensitive data filtering, and GitHub Actions annotations."""

import logging
import sys
from collections.abc import Iterator

import pytest

from bcbench_core.logs import GitHubActionsHandler, GitHubActionsSkipFilter, SensitiveDataFilter, setup_logging


class TestSensitiveDataFilter:
    @pytest.fixture
    def filter_instance(self):
        return SensitiveDataFilter()

    def test_redact_value_with_password(self, filter_instance):
        input_value = "password=secret123"
        result = filter_instance._redact_value(input_value)
        assert "secret123" not in result
        assert "******" in result

    def test_redact_value_with_bearer_token(self, filter_instance):
        input_value = "Authorization: Bearer abc123def456"
        result = filter_instance._redact_value(input_value)
        assert "abc123def456" not in result
        assert "******" in result

    def test_redact_value_with_non_string(self, filter_instance):
        assert filter_instance._redact_value(42) == 42

        assert filter_instance._redact_value(None) is None

        test_list = [1, 2, 3]
        assert filter_instance._redact_value(test_list) == test_list

    def test_redact_value_with_clean_string(self, filter_instance):
        clean_string = "This is a normal log message"
        result = filter_instance._redact_value(clean_string)
        assert result == clean_string

    def test_redact_value_with_powershell_password(self, filter_instance):
        input_value = "$password = ConvertTo-SecureString 'MySecret123' -AsPlainText -Force"
        result = filter_instance._redact_value(input_value)
        assert "MySecret123" not in result
        assert "******" in result
        assert "-AsPlainText -Force" in result  # Command flags should remain

    def test_filter_redacts_mapping_args(self, filter_instance):
        record = logging.LogRecord("test", logging.INFO, "test.py", 1, "%(cmd)s", ({"cmd": "password=hunter2"},), None)

        filter_instance.filter(record)

        assert "hunter2" not in record.getMessage()

    def test_filter_redacts_positional_args(self, filter_instance):
        record = logging.LogRecord("test", logging.INFO, "test.py", 1, "%s %s", ("password=hunter2", 7), None)

        filter_instance.filter(record)

        assert "hunter2" not in record.getMessage()
        assert record.getMessage().endswith(" 7")


class TestGitHubActionsHandler:
    @pytest.fixture
    def handler(self):
        return GitHubActionsHandler()

    @pytest.fixture
    def log_record(self):
        return logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

    def test_emit_warning_annotation(self, handler, log_record, capsys):
        handler.emit(log_record)
        captured = capsys.readouterr()
        assert "::warning title=test.logger::Test message" in captured.out

    def test_emit_error_annotation(self, handler, log_record, capsys):
        log_record.levelno = logging.ERROR
        handler.emit(log_record)
        captured = capsys.readouterr()
        assert "::error title=test.logger::Test message" in captured.out

    def test_skips_info_level(self, handler, log_record, capsys):
        log_record.levelno = logging.INFO
        handler.emit(log_record)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_escapes_special_characters(self, handler, log_record, capsys):
        log_record.msg = "Test with %percent and\nnewline"
        handler.emit(log_record)
        captured = capsys.readouterr()
        assert "%25percent" in captured.out
        assert "%0A" in captured.out

    def test_multiline_message_is_single_line_output(self, handler, log_record, capsys):
        log_record.msg = "First line\nSecond line\nThird line"
        handler.emit(log_record)
        captured = capsys.readouterr()
        # The entire annotation should be on a single line (newlines escaped)
        lines = captured.out.strip().split("\n")
        assert len(lines) == 1
        assert "First line%0ASecond line%0AThird line" in lines[0]

    def test_marks_record_as_handled(self, handler, log_record, capsys):
        handler.emit(log_record)
        assert getattr(log_record, "gh_actions_handled", False) is True

    def test_formatting_errors_do_not_propagate(self, handler, log_record, monkeypatch):
        monkeypatch.setattr(logging, "raiseExceptions", False)
        log_record.msg = "%s %s"
        log_record.args = ("only one",)

        handler.emit(log_record)


class TestGitHubActionsSkipFilter:
    @pytest.fixture
    def filter_instance(self):
        return GitHubActionsSkipFilter()

    @pytest.fixture
    def log_record(self):
        return logging.LogRecord(
            name="test.logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

    def test_allows_unhandled_records(self, filter_instance, log_record):
        assert filter_instance.filter(log_record) is True

    def test_skips_handled_records(self, filter_instance, log_record):
        log_record.gh_actions_handled = True
        assert filter_instance.filter(log_record) is False


class TestSetupLogging:
    @pytest.fixture(autouse=True)
    def isolated_logging(self) -> Iterator[None]:
        root = logging.getLogger()
        root_handlers = root.handlers[:]
        root_level = root.level
        configured_levels = {name: logging.getLogger(name).level for name in ("myapp", "bcbench_core")}

        yield

        # Remove only the handlers setup_logging installed; pytest manages its own capture handlers
        for handler in root.handlers[:]:
            if handler not in root_handlers:
                root.removeHandler(handler)
        root.setLevel(root_level)
        for name, level in configured_levels.items():
            logging.getLogger(name).setLevel(level)

    def test_application_loggers_log_info_while_third_party_stays_at_warning(self, capsys):
        setup_logging(app_loggers=("myapp",), debug=False, github_actions=False)

        logging.getLogger("myapp.evaluate").info("app info")
        logging.getLogger("bcbench_core.projects").info("core info")
        logging.getLogger("urllib3").info("library info")
        logging.getLogger("bcbench_core.projects").debug("core debug")

        err = capsys.readouterr().err
        assert "app info" in err
        assert "core info" in err
        assert "library info" not in err
        assert "core debug" not in err

    def test_debug_enables_debug_for_application_loggers(self, capsys):
        setup_logging(app_loggers=("myapp",), debug=True, github_actions=False)

        logging.getLogger("myapp.evaluate").debug("app debug")
        logging.getLogger("bcbench_core.projects").debug("core debug")

        err = capsys.readouterr().err
        assert "app debug" in err
        assert "core debug" in err

    def test_github_actions_annotates_errors_without_duplicating_console_output(self, capsys):
        setup_logging(app_loggers=("myapp",), debug=False, github_actions=True)

        logging.getLogger("bcbench_core.projects").error("categorization failed")

        captured = capsys.readouterr()
        assert "::error title=bcbench_core.projects::categorization failed" in captured.out
        assert "categorization failed" not in captured.err

    def test_repeated_setup_replaces_its_handlers_without_duplicating_output(self, capsys):
        setup_logging(app_loggers=("myapp",), debug=False, github_actions=True)
        setup_logging(app_loggers=("myapp",), debug=False, github_actions=False)

        logging.getLogger("myapp").info("once")
        logging.getLogger("myapp").error("not annotated")

        captured = capsys.readouterr()
        assert captured.err.count("once") == 1
        assert captured.err.count("not annotated") == 1
        assert "::error" not in captured.out

    def test_keeps_handlers_it_did_not_install(self, capsys):
        foreign = logging.StreamHandler(sys.stdout)
        logging.getLogger().addHandler(foreign)

        setup_logging(app_loggers=("myapp",), debug=False, github_actions=False)
        logging.getLogger("myapp").warning("seen by both")

        assert foreign in logging.getLogger().handlers
        assert "seen by both" in capsys.readouterr().out
