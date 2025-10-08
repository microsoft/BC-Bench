"""Utilities for loading dataset entries from JSONL files."""

import json
from pathlib import Path
from typing import List, Optional, Callable

from bcbench.dataset.dataset_entry import DatasetEntry

__all__ = ["load_dataset_entries"]


def load_dataset_entries(
    dataset_path: Path,
    entry_id: Optional[str] = None,
    version: Optional[str] = None,
    filter_fn: Optional[Callable] = None,
) -> List[DatasetEntry]:
    """
    Load dataset entries from a JSONL file with optional filtering.

    Args:
        dataset_path: Path to the dataset JSONL file
        entry_id: Optional instance_id to load a single specific entry
        version: Optional environment_setup_version to filter entries
        filter_fn: Optional custom filter function that takes a DatasetEntry and returns bool

    Returns:
        List of DatasetEntry objects matching the filters

    Raises:
        ValueError: If entry_id specified but not found, or if no entries match filters
        FileNotFoundError: If dataset_path doesn't exist
        json.JSONDecodeError: If JSONL file contains invalid JSON

    Examples:
        # Load a single entry by ID
        entries = load_dataset_entries(path, entry_id="NAV_12345")

        # Load all entries for a version
        entries = load_dataset_entries(path, version="v1.0")

        # Load with custom filter
        entries = load_dataset_entries(path, filter_fn=lambda e: len(e.project_paths) > 1)
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    entries: List[DatasetEntry] = []

    with open(dataset_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                entry = DatasetEntry.from_json(json.loads(line))

                # If searching for specific entry_id, return immediately when found
                if entry_id:
                    if entry.instance_id == entry_id:
                        return [entry]
                    continue

                # Apply version filter if specified
                if version and entry.environment_setup_version != version:
                    continue

                # Apply custom filter if specified
                if filter_fn and not filter_fn(entry):
                    continue

                entries.append(entry)

            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(f"Invalid JSON on line {line_num}: {e.msg}", e.doc, e.pos)
            except Exception as e:
                # Re-raise with line context
                raise ValueError(f"Error processing line {line_num}: {e}") from e

    # Check if specific entry was requested but not found
    if entry_id:
        raise ValueError(f"Entry with instance_id '{entry_id}' not found in dataset")

    # If we have filters and no results, raise an error
    if (version or filter_fn) and not entries:
        if version:
            raise ValueError(f"No entries found for version '{version}'")
        else:
            raise ValueError("No entries matched the filter criteria")

    return entries
