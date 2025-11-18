"""Helper module for PR security review evaluation."""

from __future__ import annotations

from pathlib import Path

from bcbench.agent.copilot.prompt import build_pr_review_prompt
from bcbench.dataset import PRDatasetEntry, load_pr_dataset_entries
from bcbench.operations.instruction_operations import load_instructions_template

__all__ = [
    "load_pr_dataset",
    "build_pr_security_review_prompt",
]


def load_pr_dataset(dataset_path: Path | str | None = None) -> list[PRDatasetEntry]:
    """Load PR dataset from prdataset.jsonl.

    Args:
        dataset_path: Path to prdataset.jsonl. If None, uses default from config.

    Returns:
        List of PRDatasetEntry objects
    """
    if dataset_path is None:
        from bcbench.config import get_config

        config = get_config()
        dataset_path = config.paths.bc_bench_root / "dataset" / "prdataset.jsonl"

    return load_pr_dataset_entries(dataset_path)


def build_pr_security_review_prompt(
    pr_entry: PRDatasetEntry,
    instructions_path: Path | str | None = None,
) -> str:
    """Build complete PR security review prompt with instructions and PR data.

    Loads the instructions template and replaces placeholders with PR data.

    Args:
        pr_entry: PR dataset entry
        instructions_path: Path to instructions.md. If None, uses default.

    Returns:
        Complete prompt ready for the AI agent

    Raises:
        FileNotFoundError: If instructions template not found
    """
    if instructions_path is None:
        instructions_template = load_instructions_template()
    else:
        path = Path(instructions_path)
        if not path.exists():
            raise FileNotFoundError(f"Instructions not found at {path}")
        with path.open("r", encoding="utf-8") as f:
            instructions_template = f.read()

    return build_pr_review_prompt(pr_entry, instructions_template)
