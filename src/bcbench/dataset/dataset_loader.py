"""Utilities for loading dataset entries from JSONL files."""

from pathlib import Path

from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.exceptions import EntryNotFoundError

__all__ = ["load_dataset_entries"]


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
            striped_line = line.strip()
            if not striped_line:
                continue

            entry = DatasetEntry.model_validate_json(striped_line)

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
