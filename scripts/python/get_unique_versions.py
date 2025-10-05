#!/usr/bin/env python3
"""
Extract unique environment setup versions from the BC-Bench dataset.

This script reads the bcbench_nav.jsonl dataset file and returns all unique
environment_setup_version values as a JSON array, suitable for use in
GitHub Actions matrix strategy.
"""

import json
import logging
import sys
from pathlib import Path
from typing import List, Set

from dataset_entry import DatasetEntry
from utils import DATASET_PATH


def get_unique_versions(dataset_path: Path) -> List[str]:
    """
    Extract unique environment setup versions from the dataset.

    Args:
        dataset_path: Path to the bcbench_nav.jsonl dataset file

    Returns:
        List of unique environment setup versions, sorted

    Raises:
        FileNotFoundError: If the dataset file doesn't exist
        Exception: If there's an error reading or parsing the dataset
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    versions: Set[str] = set()

    try:
        with open(dataset_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    entry = DatasetEntry.from_json(data)

                    # Add version if it's not empty
                    if entry.environment_setup_version:
                        versions.add(entry.environment_setup_version)

                except json.JSONDecodeError as e:
                    logging.warning(f"Invalid JSON on line {line_num}: {e}")
                except Exception as e:
                    logging.warning(f"Error processing line {line_num}: {e}")

    except Exception as e:
        raise Exception(f"Failed to read dataset file: {e}")

    # Return sorted list for consistent ordering
    return sorted(list(versions))


def main():
    # Use command line argument if provided, otherwise use default from utils
    if len(sys.argv) > 1:
        dataset_path = Path(sys.argv[1])
    else:
        dataset_path = DATASET_PATH

    try:
        versions = get_unique_versions(dataset_path)

        # Output as JSON array for GitHub Actions matrix
        print(json.dumps(versions))

        # Log summary to stderr so it doesn't interfere with JSON output
        logging.info(f"Found {len(versions)} unique versions: {', '.join(versions)}")

    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()