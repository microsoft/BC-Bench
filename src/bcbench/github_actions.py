"""Helpers for interacting with GitHub Actions.

These wrap GitHub Actions workflow features (step outputs, log groups) and are no-ops when not running inside Actions.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bcbench.logger import get_logger

__all__ = ["github_log_group", "write_step_outputs"]

logger = get_logger(__name__)


def write_step_outputs(outputs: dict[str, str], *, output_path: Path | None) -> None:
    """Append ``key=value`` step outputs to the GitHub Actions output file.

    The values become outputs of the current workflow step, available to downstream steps via ``steps.<id>.outputs.<key>``.

    Args:
        outputs: Mapping of output names to their string values.

    Note:
        When not running inside GitHub Actions (``$GITHUB_OUTPUT`` is unset), nothing is written and a warning is logged.
    """
    if output_path is None:
        logger.warning("Not running in GitHub Actions; skipping step outputs: %s", ", ".join(outputs))
        return

    with output_path.open("a", encoding="utf-8") as file:
        file.writelines(f"{key}={value}\n" for key, value in outputs.items())


@contextmanager
def github_log_group(title: str, *, in_actions: bool = False) -> Iterator[None]:
    if in_actions:
        print(f"::group::{title}", flush=True)  # noqa: T201

    try:
        yield
    finally:
        if in_actions:
            print("::endgroup::", flush=True)  # noqa: T201
