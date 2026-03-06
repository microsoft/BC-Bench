"""Utilities for loading dataset entries from JSONL files."""

import json
from pathlib import Path

from bcbench.dataset.dataset_entry import BugFixEntry, DatasetEntry, TestGenerationEntry
from bcbench.exceptions import EntryNotFoundError
from bcbench.types import EvaluationCategory

__all__ = ["load_dataset_entries"]


def _parse_entry(data: dict) -> DatasetEntry:
    category = EvaluationCategory(data.get("category", EvaluationCategory.BUG_FIX.value))
    match category:
        case EvaluationCategory.BUG_FIX:
            return BugFixEntry.model_validate(data)
        case EvaluationCategory.TEST_GENERATION:
            return TestGenerationEntry.model_validate(data)
        case _:
            raise ValueError(f"Unknown dataset entry category: {category}")


def load_dataset_entries(dataset_path: Path, entry_id: str | None = None, random: int | None = None) -> list[DatasetEntry]:
    """
    Load dataset entries from a JSONL file.

    Examples:
        # Load a single entry by ID
        entries = load_dataset_entries(path, entry_id="NAV_12345")

        # Load 2 random entries
        entries = load_dataset_entries(path, random=2)
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    entries: list[DatasetEntry] = []

    with open(dataset_path, encoding="utf-8") as file:
        for line in file:
            stripped_line: str = line.strip()
            if not stripped_line:
                continue

            entry = _parse_entry(json.loads(stripped_line))

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
