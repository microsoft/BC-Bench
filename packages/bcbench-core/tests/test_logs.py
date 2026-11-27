"""Tests for logging setup, sensitive data filtering, and GitHub Actions annotations."""

import logging
import sys
from collections.abc import Iterator

import pytest

from bcbench_core.logs import AzurePipelinesFormatter, GitHubActionsFormatter, SensitiveDataFilter, setup_logging


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

    @pytest.mark.parametrize("args", [None, (), {}])
    def test_filter_preserves_empty_args(self, filter_instance, args):
        record = logging.LogRecord("test", logging.INFO, "test.py", 1, "Test message", (), None)
        record.args = args

        filter_instance.filter(record)

        assert record.args is args
        assert record.getMessage() == "Test message"


class TestCIAnnotationFormatters:
    @pytest.fixture
    def console(self) -> logging.Formatter:
        return logging.Formatter("console: %(message)s")

    @staticmethod
    def _record(level: int, msg: str, *args: object) -> logging.LogRecord:
        return logging.LogRecord("test.logger", level, "test.py", 42, msg, args, None)

    @pytest.mark.parametrize(
        ("formatter", "level", "expected"),
        [
            (GitHubActionsFormatter, logging.WARNING, "::warning title=test.logger::problem"),
            (GitHubActionsFormatter, logging.ERROR, "::error title=test.logger::problem"),
            (GitHubActionsFormatter, logging.CRITICAL, "::error title=test.logger::problem"),
            (AzurePipelinesFormatter, logging.WARNING, "##vso[task.logissue type=warning]test.logger - problem"),
            (AzurePipelinesFormatter, logging.ERROR, "##vso[task.logissue type=error]test.logger - problem"),
            (AzurePipelinesFormatter, logging.CRITICAL, "##vso[task.logissue type=error]test.logger - problem"),
        ],
    )
    def test_formats_warnings_and_errors_as_annotations(self, console, formatter, level, expected):
        assert formatter(console).format(self._record(level, "problem")) == expected

    @pytest.mark.parametrize("formatter", [GitHubActionsFormatter, AzurePipelinesFormatter])
    @pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO])
    def test_delegates_lower_levels_to_console_formatter(self, console, formatter, level):
        assert formatter(console).format(self._record(level, "progress")) == "console: progress"

    @pytest.mark.parametrize(
        ("formatter", "expected"),
        [
            (GitHubActionsFormatter, "::warning title=test.logger::100%25 %250A%0D%0Anext"),
            (AzurePipelinesFormatter, "##vso[task.logissue type=warning]test.logger - 100%AZP25 %AZP250A%0D%0Anext"),
        ],
    )
    def test_escapes_percent_and_newlines_into_a_single_line(self, console, formatter, expected):
        assert formatter(console).format(self._record(logging.WARNING, "100% %0A\r\nnext")) == expected

    def test_azure_pipelines_neutralizes_logging_commands_in_annotation_body(self, console):
        formatted = AzurePipelinesFormatter(console).format(self._record(logging.ERROR, "model said ##vso[task.complete]"))

        assert formatted == "##vso[task.logissue type=error]test.logger - model said #\u200b#vso[task.complete]"


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
        setup_logging(app_logger="myapp", debug=False, github_actions=False, azure_pipelines=False)

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
        setup_logging(app_logger="myapp", debug=True, github_actions=False, azure_pipelines=False)

        logging.getLogger("myapp.evaluate").debug("app debug")
        logging.getLogger("bcbench_core.projects").debug("core debug")

        err = capsys.readouterr().err
        assert "app debug" in err
        assert "core debug" in err

    def test_repeated_setup_replaces_its_handler_without_duplicating_output(self, capsys):
        setup_logging(app_logger="myapp", debug=False, github_actions=True, azure_pipelines=False)
        setup_logging(app_logger="myapp", debug=False, github_actions=False, azure_pipelines=False)

        logging.getLogger("myapp").info("once")
        logging.getLogger("myapp").error("not annotated")

        err = capsys.readouterr().err
        assert err.count("once") == 1
        assert err.count("not annotated") == 1
        assert "::error" not in err

    def test_keeps_handlers_it_did_not_install(self, capsys):
        foreign = logging.StreamHandler(sys.stdout)
        logging.getLogger().addHandler(foreign)

        setup_logging(app_logger="myapp", debug=False, github_actions=False, azure_pipelines=False)
        logging.getLogger("myapp").warning("seen by both")

        assert foreign in logging.getLogger().handlers
        assert "seen by both" in capsys.readouterr().out

    @pytest.mark.parametrize(
        ("github_actions", "azure_pipelines", "expected"),
        [
            (True, False, "::warning title=myapp::problem\n"),
            (False, True, "##vso[task.logissue type=warning]myapp - problem\n"),
        ],
    )
    def test_ci_annotations_go_to_stderr_once_and_keep_stdout_clean(self, github_actions, azure_pipelines, expected, capsys):
        setup_logging(app_logger="myapp", debug=False, github_actions=github_actions, azure_pipelines=azure_pipelines)

        logging.getLogger("myapp").warning("problem")

        captured = capsys.readouterr()
        assert captured.err == expected
        assert captured.out == ""

    def test_rejects_both_ci_platforms(self):
        with pytest.raises(ValueError, match="mutually exclusive"):
            setup_logging(app_logger="myapp", debug=False, github_actions=True, azure_pipelines=True)

    def test_ci_annotations_redact_secrets(self, capsys):
        setup_logging(app_logger="myapp", debug=False, github_actions=False, azure_pipelines=True)

        logging.getLogger("myapp").error("login failed with %s", "password=hunter2")

        assert capsys.readouterr().err == "##vso[task.logissue type=error]myapp - login failed with password=******\n"

    def test_azure_pipelines_neutralizes_logging_commands_in_messages_args_and_tracebacks(self, capsys):
        setup_logging(app_logger="myapp", debug=False, github_actions=False, azure_pipelines=True)

        logging.getLogger("myapp").info("model said ##vso[task.setvariable variable=x]1 and %s", "##[group]")
        try:
            _fail("###vso[task.complete]")
        except ValueError:
            logging.getLogger("myapp").exception("failed")

        err = capsys.readouterr().err
        info, annotation = err.splitlines()
        assert "#\u200b#vso[task.setvariable variable=x]1 and #\u200b#[group]" in info
        assert annotation.startswith("##vso[task.logissue type=error]myapp - failed%0ATraceback")
        assert "ValueError: #\u200b#\u200b#vso[task.complete]" in annotation
        assert err.count("##") == 1


def _fail(message: str) -> None:
    raise ValueError(message)
