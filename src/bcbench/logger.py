"""Unified logging configuration for bcbench."""

import logging
import os
import re
import sys
from contextlib import contextmanager
from typing import ClassVar

from bcbench.config import get_config

__all__ = ["get_logger", "github_log_group", "setup_logger"]


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

    def _redact_value(self, value):
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
        logging.DEBUG: GREY + "[%(asctime)s] %(name)s - %(message)s" + RESET,
        logging.INFO: "[%(asctime)s] %(name)s - %(message)s",
        logging.WARNING: YELLOW + "[%(asctime)s] %(name)s - %(message)s" + RESET,
        logging.ERROR: RED + "[%(asctime)s] %(name)s - %(message)s" + RESET,
        logging.CRITICAL: RED + "[%(asctime)s] %(name)s - CRITICAL: %(message)s" + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


class GitHubActionsHandler(logging.Handler):
    """Handler that emits GitHub Actions workflow commands for warnings and errors."""

    def emit(self, record: logging.LogRecord) -> None:
        """Emit a GitHub Actions annotation for warning and error level logs."""
        try:
            # Only emit annotations for warnings and errors
            if record.levelno < logging.WARNING:
                return

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
            print(annotation, flush=True)

        except Exception:
            self.handleError(record)


_logging_configured = False


def setup_logger(verbose: bool = False) -> None:
    """
    Configure logging for the entire bcbench package.

    Args:
        verbose: If True, set bcbench loggers to DEBUG level, otherwise INFO.
    """
    global _logging_configured  # noqa: PLW0603

    if _logging_configured:
        return

    config = get_config()

    # Suppress mini-swe-agent startup message
    # This prevents encoding errors from emoji characters on Windows
    os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")

    bcbench_level = logging.DEBUG if verbose else logging.INFO

    # Check for GitHub Actions debug mode
    if config.env.runner_debug:
        bcbench_level = logging.DEBUG

    # Configure root logger (for 3rd party libraries) to WARNING
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler with colored formatter and sensitive data filter
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(ColoredFormatter())
    console_handler.addFilter(SensitiveDataFilter())
    root_logger.addHandler(console_handler)

    # Add GitHub Actions handler if running in GitHub Actions
    if config.env.github_actions:
        github_handler = GitHubActionsHandler()
        github_handler.setLevel(logging.WARNING)  # Only warnings and errors
        github_handler.setFormatter(logging.Formatter("%(message)s"))
        github_handler.addFilter(SensitiveDataFilter())
        root_logger.addHandler(github_handler)

    # Configure bcbench loggers to use the desired level
    bcbench_logger = logging.getLogger("bcbench")
    bcbench_logger.setLevel(bcbench_level)

    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    # Ensure name starts with 'bcbench.' for proper hierarchy
    if not name.startswith("bcbench.") and name != "bcbench":
        name = f"bcbench.{name}"

    return logging.getLogger(name)


@contextmanager
def github_log_group(title: str):
    config = get_config()

    if config.env.github_actions:
        print(f"::group::{title}", flush=True)

    try:
        yield
    finally:
        if config.env.github_actions:
            print("::endgroup::", flush=True)
