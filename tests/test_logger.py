"""Tests for logger module, focusing on sensitive data filtering."""

import logging

import pytest

from bcbench.logger import GitHubActionsHandler, SensitiveDataFilter


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
