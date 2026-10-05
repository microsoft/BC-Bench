import logging

__all__ = ["get_logger"]


def get_logger(name: str) -> logging.Logger:
    # Ensure name starts with 'bcbench.' for proper hierarchy
    if not name.startswith("bcbench.") and name != "bcbench":
        name = f"bcbench.{name}"

    return logging.getLogger(name)
