#!/usr/bin/env python3
"""Validate all entries in the BC-Bench dataset against the JSON schema."""

import json
from pathlib import Path
from typing import List, Tuple

import typer

from bcbench.core.dataset_entry import DatasetEntry
from bcbench.core.utils import DATASET_PATH, DATASET_SCHEMA_PATH
from bcbench.core.logger import get_logger

logger = get_logger(__name__)


def validate_dataset(dataset_path: Path = DATASET_PATH) -> Tuple[int, int, List[str]]:
    """
    Validate all dataset entries.

    Args:
        dataset_path: Path to the dataset file to validate

    Returns:
        Tuple of (total_entries, failed_entries, error_messages)
    """
    total_entries: int = 0
    failed_entries: int = 0

    if not dataset_path.exists():
        logger.error(f"Dataset file not found at {dataset_path}")
        return (
            total_entries,
            failed_entries,
            [f"Dataset file not found at {dataset_path}"],
        )

    if not DATASET_SCHEMA_PATH.exists():
        logger.error(f"Schema file not found at {DATASET_SCHEMA_PATH}")
        return (
            total_entries,
            failed_entries,
            [f"Schema file not found at {DATASET_SCHEMA_PATH}"],
        )

    error_messages = []

    logger.info(f"Validating dataset: {dataset_path}")
    logger.info(f"Using schema: {DATASET_SCHEMA_PATH}")
    print("-" * 50)

    try:
        with open(dataset_path, "r", encoding="utf-8") as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if not line:
                    continue

                total_entries += 1

                try:
                    # Parse JSON from line
                    json_data = json.loads(line)

                    # Create DatasetEntry and validate
                    entry = DatasetEntry.from_json(json_data)
                    entry.validate(DATASET_SCHEMA_PATH)

                    print(f"[OK] Entry {total_entries}: {entry.instance_id}")

                except json.JSONDecodeError as e:
                    failed_entries += 1
                    error_msg = f"Line {line_num}: JSON decode error - {str(e)}"
                    error_messages.append(error_msg)
                    print(f"[ERROR] {error_msg}")

                except ValueError as e:
                    failed_entries += 1
                    error_msg = f"Line {line_num}: Validation error - {str(e)}"
                    error_messages.append(error_msg)
                    print(f"[ERROR] {error_msg}")

                except Exception as e:
                    failed_entries += 1
                    error_msg = f"Line {line_num}: Unexpected error - {str(e)}"
                    error_messages.append(error_msg)
                    print(f"[ERROR] {error_msg}")

    except FileNotFoundError as e:
        error_msg = f"File not found: {str(e)}"
        error_messages.append(error_msg)
        print(f"Error: {error_msg}")
        return total_entries, failed_entries, error_messages

    except Exception as e:
        error_msg = f"Unexpected error reading dataset: {str(e)}"
        error_messages.append(error_msg)
        print(f"Error: {error_msg}")
        return total_entries, failed_entries, error_messages

    return total_entries, failed_entries, error_messages


def validate_dataset_file(dataset_path: Path) -> None:
    """
    Main entry point for dataset validation.

    Args:
        dataset_path: Path to the dataset file (defaults to DATASET_PATH)

    Raises:
        typer.Exit: Exits with code 1 on validation failure
    """
    print("BC-Bench Dataset Validation")
    print("=" * 50)

    total, failed, errors = validate_dataset(dataset_path)

    print("-" * 50)
    print("VALIDATION SUMMARY:")
    print(f"Total entries processed: {total}")
    print(f"Successful validations: {total - failed}")
    print(f"Failed validations: {failed}")

    if failed > 0:
        print("\nERROR DETAILS:")
        for error in errors:
            print(f"  - {error}")

        logger.error(
            f"Dataset validation failed: {failed} out of {total} entries have errors"
        )
        raise typer.Exit(code=1)
    else:
        logger.info(f"Dataset validation successful: All {total} entries are valid")
