"""Utilities for loading dataset entries from JSONL files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bcbench.dataset.base import BaseDatasetEntry, create_entry_from_json
from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.exceptions import EntryNotFoundError

if TYPE_CHECKING:
    from bcbench.types import EvaluationCategory

__all__ = ["load_dataset_entries"]


def load_dataset_entries(
    dataset_path: Path,
    entry_id: str | None = None,
    random: int | None = None,
    category: EvaluationCategory | None = None,
) -> list[BaseDatasetEntry]:
    """
    Load dataset entries from a JSONL file.

    When category is provided, creates category-specific entry instances via factory.
    When category is None, creates DatasetEntry instances (backward compatible).

    Examples:
        # Load a single entry by ID
        entries = load_dataset_entries(path, entry_id="NAV_12345")

        # Load 2 random entries
        entries = load_dataset_entries(path, random=2)

        # Load entries for a specific category
        entries = load_dataset_entries(path, category=EvaluationCategory.BUG_FIX)
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    entries: list[BaseDatasetEntry] = []

    with open(dataset_path, encoding="utf-8") as file:
        for line in file:
            stripped_line: str = line.strip()
            if not stripped_line:
                continue

            entry = create_entry_from_json(stripped_line, category) if category is not None else DatasetEntry.model_validate_json(stripped_line)

            # If searching for specific entry_id, return immediately when found
            if entry_id:
                if entry.instance_id == entry_id:
                    return [entry]
                continue

            entries.append(entry)

    if entry_id:
        raise EntryNotFoundError(entry_id)

    if random is not None and random > 0:
        import random as random_module

        return random_module.sample(entries, min(random, len(entries)))

    return entries
