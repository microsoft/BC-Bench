"""Opt-in logging configuration for applications built on bcbench-core."""

import logging
import re
import sys
from typing import ClassVar, override

__all__ = ["setup_logging"]


class SensitiveDataFilter(logging.Filter):
    """Filter that automatically redacts sensitive information from log messages."""

    # Patterns for detecting and redacting sensitive data
    PATTERNS: ClassVar = [
        # PowerShell ConvertTo-SecureString password assignments
        # Matches: $password = ConvertTo-SecureString 'secret' -AsPlainText -Force
        (
            re.compile(
                r"(\$password\s*=\s*ConvertTo-SecureString\s*['\"])[^'\"]*(['\"]\s*-AsPlainText\s*-Force)",
                re.IGNORECASE,
            ),
            r"\1******\2",
        ),
        # Generic password assignments (various formats)
        # Matches: password='secret', password="secret", password=secret
        (
            re.compile(r"(password\s*[=:]\s*['\"]?)[^\s'\"]+(['\"]?)", re.IGNORECASE),
            r"\1******\2",
        ),
        # Bearer tokens and API keys
        # Matches: Authorization: Bearer token, api_key=abc123
        (
            re.compile(r"(bearer\s+)[a-zA-Z0-9._\-]+", re.IGNORECASE),
            r"\1******",
        ),
        (
            re.compile(r"(api[_\-]?key\s*[=:]\s*['\"]?)[^\s'\"]+", re.IGNORECASE),
            r"\1******",
        ),
        # Authorization headers
        # Matches: Authorization: Basic base64string
        (
            re.compile(r"(Authorization\s*:\s*\w+\s+)[^\s]+", re.IGNORECASE),
            r"\1******",
        ),
    ]

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """Redact sensitive information from the log record's message."""
        if isinstance(record.msg, str):
            # Apply all redaction patterns
            redacted_msg = record.msg
            for pattern, replacement in self.PATTERNS:
                redacted_msg = pattern.sub(replacement, redacted_msg)
            record.msg = redacted_msg

        # Also redact from args if present
        if bool(record.args):
            if isinstance(record.args, dict):
                record.args = {key: self._redact_value(value) for key, value in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact_value(arg) for arg in record.args)

        return True

    def _redact_value(self, value: object) -> object:
        """Redact sensitive information from a single value."""
        if isinstance(value, str):
            redacted = value
            for pattern, replacement in self.PATTERNS:
                redacted = pattern.sub(replacement, redacted)
            return redacted
        return value


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels."""

    GREY = "\033[90m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    RESET = "\033[0m"

    FORMATS: ClassVar = {
        logging.DEBUG: (GREY, "[%(asctime)s] %(name)s - %(message)s"),
        logging.INFO: (None, "[%(asctime)s] %(name)s - %(message)s"),
        logging.WARNING: (YELLOW, "[%(asctime)s] %(name)s - %(message)s"),
        logging.ERROR: (RED, "[%(asctime)s] %(name)s - %(message)s"),
        logging.CRITICAL: (RED, "[%(asctime)s] %(name)s - CRITICAL: %(message)s"),
    }

    @override
    def format(self, record: logging.LogRecord) -> str:
        color, log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        formatted = formatter.format(record)

        # Apply color to each line for multiline messages
        if color:
            lines = formatted.split("\n")
            formatted = "\n".join(f"{color}{line}{self.RESET}" for line in lines)

        return formatted


class AzurePipelinesSafeFormatter(logging.Formatter):
    """Formatter that breaks up "##" so logged text, such as model output, cannot run as an Azure Pipelines logging command (##vso[, ##[)."""

    _ADJACENT_HASH: ClassVar[re.Pattern[str]] = re.compile(r"#(?=#)")

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self._inner = inner

    @override
    def format(self, record: logging.LogRecord) -> str:
        # Every adjacent pair, not each "##" match, so runs like "###vso[" keep no live "##" prefix
        return self._ADJACENT_HASH.sub("#\u200b", self._inner.format(record))


class CIAnnotationFormatter(logging.Formatter):
    """Formats warnings and errors as CI annotations and delegates other levels to the console formatter."""

    def __init__(self, console: logging.Formatter) -> None:
        super().__init__()
        self._console = console

    @override
    def format(self, record: logging.LogRecord) -> str:
        if record.levelno < logging.WARNING:
            return self._console.format(record)
        return self.annotate("error" if record.levelno >= logging.ERROR else "warning", record)

    def annotate(self, issue: str, record: logging.LogRecord) -> str:
        raise NotImplementedError


class GitHubActionsFormatter(CIAnnotationFormatter):
    _ESCAPES: ClassVar[dict[int, str]] = str.maketrans({"%": "%25", "\r": "%0D", "\n": "%0A"})

    @override
    def annotate(self, issue: str, record: logging.LogRecord) -> str:
        message = logging.Formatter("%(message)s").format(record)
        return f"::{issue} title={record.name.translate(self._ESCAPES)}::{message.translate(self._ESCAPES)}"


class AzurePipelinesFormatter(CIAnnotationFormatter):
    _ESCAPES: ClassVar[dict[int, str]] = str.maketrans({"%": "%AZP25", "\r": "%0D", "\n": "%0A"})

    @override
    def annotate(self, issue: str, record: logging.LogRecord) -> str:
        body = AzurePipelinesSafeFormatter(logging.Formatter("%(name)s - %(message)s")).format(record)
        return f"##vso[task.logissue type={issue}]{body.translate(self._ESCAPES)}"


_CORE_LOGGER = __name__.partition(".")[0]
_CONSOLE_HANDLER_NAME = f"{_CORE_LOGGER}.console"


def setup_logging(app_logger: str, debug: bool, github_actions: bool, azure_pipelines: bool) -> None:
    """Configure process-wide logging; call once from the application entry point.

    Calling again replaces the handler installed by a previous call; other root handlers are kept.
    All output, including CI annotations, goes to stderr so stdout stays free for command results.

    Args:
        app_logger: Top-level logger name of the application, usually its package name; bcbench-core's logger is always included.
        debug: If True, set application and bcbench-core loggers to DEBUG level, otherwise INFO.
        github_actions: If True, emit warnings and errors as GitHub Actions annotations.
        azure_pipelines: If True, emit warnings and errors as Azure Pipelines annotations and neutralize logging commands in all output.

    Raises:
        ValueError: If both github_actions and azure_pipelines are True.
    """
    if github_actions and azure_pipelines:
        raise ValueError("github_actions and azure_pipelines are mutually exclusive")

    app_level = logging.DEBUG if debug else logging.INFO

    # Configure root logger (for 3rd party libraries) to WARNING
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)

    for handler in root_logger.handlers[:]:
        if handler.get_name() == _CONSOLE_HANDLER_NAME:
            root_logger.removeHandler(handler)
            handler.close()

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.set_name(_CONSOLE_HANDLER_NAME)
    console_handler.setFormatter(_console_formatter(github_actions, azure_pipelines))
    console_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(console_handler)

    for name in (app_logger, _CORE_LOGGER):
        logging.getLogger(name).setLevel(app_level)


def _console_formatter(github_actions: bool, azure_pipelines: bool) -> logging.Formatter:
    if github_actions:
        return GitHubActionsFormatter(ColoredFormatter())
    if azure_pipelines:
        return AzurePipelinesFormatter(AzurePipelinesSafeFormatter(ColoredFormatter()))
    return ColoredFormatter()
