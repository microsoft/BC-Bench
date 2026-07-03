"""Helpers for interacting with GitHub Actions.

These wrap GitHub Actions workflow features (step outputs, log groups) and are no-ops when not running inside Actions.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from bcbench.config import get_config
from bcbench.logger import get_logger

__all__ = ["github_log_group", "write_step_outputs"]

logger = get_logger(__name__)


def write_step_outputs(outputs: dict[str, str]) -> None:
    """Append ``key=value`` step outputs to the GitHub Actions output file.

    The values become outputs of the current workflow step, available to downstream steps via ``steps.<id>.outputs.<key>``.

    Args:
        outputs: Mapping of output names to their string values.

    Note:
        When not running inside GitHub Actions (``$GITHUB_OUTPUT`` is unset), nothing is written and a warning is logged.
    """
    github_output: str | None = os.getenv("GITHUB_OUTPUT")
    if not github_output:
        logger.warning("Not running in GitHub Actions; skipping step outputs: %s", ", ".join(outputs))
        return

    with open(github_output, "a", encoding="utf-8") as file:
        file.writelines(f"{key}={value}\n" for key, value in outputs.items())


@contextmanager
def github_log_group(title: str) -> Iterator[None]:
    in_actions: bool = get_config().env.github_actions

    if in_actions:
        print(f"::group::{title}", flush=True)  # noqa: T201

    try:
        yield
    finally:
        if in_actions:
            print("::endgroup::", flush=True)  # noqa: T201
