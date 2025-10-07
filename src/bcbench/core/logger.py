"""Unified logging configuration for bcbench."""

import logging
import os
import sys

__all__ = ["setup_logger", "get_logger"]

# ANSI color codes for terminal output
GREY = "\033[90m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for different log levels."""

    FORMATS = {
        logging.DEBUG: GREY + "[%(asctime)s] %(name)s - %(message)s" + RESET,
        logging.INFO: "[%(asctime)s] %(name)s - %(message)s",
        logging.WARNING: YELLOW + "[%(asctime)s] %(name)s - %(message)s" + RESET,
        logging.ERROR: RED + "[%(asctime)s] %(name)s - %(message)s" + RESET,
        logging.CRITICAL: RED
        + "[%(asctime)s] %(name)s - CRITICAL: %(message)s"
        + RESET,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        formatter = logging.Formatter(log_fmt, datefmt="%H:%M:%S")
        return formatter.format(record)


_logging_configured = False


def setup_logger(verbose: bool = False) -> None:
    """
    Configure logging for the entire bcbench package.

    Args:
        verbose: If True, set bcbench loggers to DEBUG level, otherwise INFO.
    """
    global _logging_configured

    if _logging_configured:
        return

    bcbench_level = logging.DEBUG if verbose else logging.INFO

    # Check for GitHub Actions debug mode
    if os.environ.get("RUNNER_DEBUG") == "1":
        bcbench_level = logging.DEBUG

    # Configure root logger (for 3rd party libraries) to WARNING
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler with colored formatter
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(ColoredFormatter())
    root_logger.addHandler(console_handler)

    # Configure bcbench loggers to use the desired level
    bcbench_logger = logging.getLogger("bcbench")
    bcbench_logger.setLevel(bcbench_level)

    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: The name of the module (typically __name__).

    Returns:
        A configured logger instance.
    """
    # Ensure name starts with 'bcbench.' for proper hierarchy
    if not name.startswith("bcbench.") and name != "bcbench":
        name = f"bcbench.{name}"

    return logging.getLogger(name)
