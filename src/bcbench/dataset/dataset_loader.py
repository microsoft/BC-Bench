"""Utilities for loading dataset entries from JSONL files."""

import json
from pathlib import Path
from typing import Union

import yaml

from bcbench.dataset.dataset_entry import DatasetEntry, DatasetEntryV2, Dataset
from bcbench.exceptions import EntryNotFoundError

__all__ = ["load_dataset_entries"]


def load_dataset_entries(dataset_path: Path, entry_id: str | None = None, random: int | None = None) -> Union[list[DatasetEntry], Dataset]:
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
        if dataset_path.suffix.lower() == ".jsonl":
            for line in file:
                striped_line = line.strip()
                if not striped_line:
                    continue

                entry = DatasetEntry.from_json(json.loads(striped_line))

                # If searching for specific entry_id, return immediately when found
                if entry_id:
                    if entry.instance_id == entry_id:
                        return [entry]
                    continue

                entries.append(entry)
        else:
            entries: list[DatasetEntryV2] = Dataset(**yaml.safe_load(file)).entries
            for entry in entries:
                if entry_id:
                    if entry.instance_id == entry_id:
                        return [entry]
                    continue

    if entry_id:
        raise EntryNotFoundError(entry_id)

    if random is not None and random > 0:
        import random as random_module

        return random_module.sample(entries, min(random, len(entries)))

    return entries
