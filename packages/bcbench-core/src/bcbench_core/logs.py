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
        if record.args:
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


class GitHubActionsHandler(logging.Handler):
    """Handler that emits GitHub Actions workflow commands for warnings and errors.

    This handler outputs annotations to GitHub Actions and marks records as handled
    to prevent duplicate output from other handlers.
    """

    @override
    def emit(self, record: logging.LogRecord) -> None:
        """Emit a GitHub Actions annotation for warning and error level logs."""
        try:
            # Only emit annotations for warnings and errors
            if record.levelno < logging.WARNING:
                return

            # Mark this record as handled by GitHub Actions to prevent duplicate output
            record.gh_actions_handled = True

            # Format the message
            msg = self.format(record)

            # Escape special characters for GitHub Actions
            # Per GitHub docs: need to escape %, \r, \n
            escape_table = str.maketrans({"%": "%25", "\r": "%0D", "\n": "%0A"})
            msg = msg.translate(escape_table)

            # Determine the command type
            command = "error" if record.levelno >= logging.ERROR else "warning"

            # Build the annotation command
            # Format: ::warning file={name},line={line},title={title}::{message}
            # Escape the logger name as well since it could contain special characters
            title = record.name.translate(escape_table)
            annotation = f"::{command} title={title}::{msg}"

            # Output to stdout (GitHub Actions reads workflow commands from stdout)
            print(annotation, flush=True)  # noqa: T201

        except Exception:  # noqa: BLE001 - a logging handler must never propagate
            self.handleError(record)


class GitHubActionsSkipFilter(logging.Filter):
    """Filter that skips records already handled by GitHubActionsHandler."""

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        """Return False if the record was already handled by GitHub Actions handler."""
        return not getattr(record, "gh_actions_handled", False)


_CORE_LOGGER = __name__.partition(".")[0]
_GITHUB_HANDLER_NAME = f"{_CORE_LOGGER}.github_actions"
_CONSOLE_HANDLER_NAME = f"{_CORE_LOGGER}.console"


def setup_logging(app_logger: str, debug: bool, github_actions: bool) -> None:
    """Configure process-wide logging; call once from the application entry point.

    Calling again replaces the handlers installed by a previous call; other root handlers are kept.

    Args:
        app_logger: Top-level logger name of the application, usually its package name; bcbench-core's logger is always included.
        debug: If True, set application and bcbench-core loggers to DEBUG level, otherwise INFO.
        github_actions: If True, also emit warnings and errors as GitHub Actions annotations.
    """
    app_level = logging.DEBUG if debug else logging.INFO

    # Configure root logger (for 3rd party libraries) to WARNING
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)

    for handler in root_logger.handlers[:]:
        if handler.get_name() in {_GITHUB_HANDLER_NAME, _CONSOLE_HANDLER_NAME}:
            root_logger.removeHandler(handler)
            handler.close()

    # Add GitHub Actions handler FIRST if running in GitHub Actions
    # This ensures records are marked before the console handler sees them
    if github_actions:
        github_handler = GitHubActionsHandler()
        github_handler.set_name(_GITHUB_HANDLER_NAME)
        github_handler.setLevel(logging.WARNING)  # Only warnings and errors
        github_handler.setFormatter(logging.Formatter("%(message)s"))
        github_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(github_handler)

    # Create console handler with colored formatter and sensitive data filter
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.set_name(_CONSOLE_HANDLER_NAME)
    console_handler.setFormatter(ColoredFormatter())
    console_handler.addFilter(SensitiveDataFilter())
    console_handler.addFilter(GitHubActionsSkipFilter())
    root_logger.addHandler(console_handler)

    for name in (app_logger, _CORE_LOGGER):
        logging.getLogger(name).setLevel(app_level)
