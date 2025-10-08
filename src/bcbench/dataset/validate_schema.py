#!/usr/bin/env python3
"""Validate all entries in the BC-Bench dataset against the JSON schema."""

import json
from dataclasses import dataclass
from pathlib import Path

import typer
from jsonschema import validate

from bcbench.core.logger import get_logger
from bcbench.dataset.dataset_loader import load_dataset_entries

logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """Structure to hold validation results for a single entry."""

    line_number: int
    instance_id: str
    success: bool
    error_message: str | None = None


def validate_dataset(dataset_path: Path, schema_path: Path) -> None:
    validateion_summary: list[ValidationResult] = []

    if not dataset_path.exists():
        logger.error(f"Dataset file not found at {dataset_path}")
        raise typer.Exit(code=1)

    if not schema_path.exists():
        logger.error(f"Schema file not found at {schema_path}")
        raise typer.Exit(code=1)

    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    logger.debug(f"Validating dataset: {dataset_path}")
    logger.debug(f"Using schema: {schema_path}")

    try:
        # Load all entries from the dataset
        entries = load_dataset_entries(dataset_path)

        for line_num, entry in enumerate(entries, 1):
            try:
                validate(instance=entry.to_dict(), schema=schema)
                result = ValidationResult(line_number=line_num, instance_id=entry.instance_id, success=True)
                validateion_summary.append(result)
                logger.debug(f"[OK] Entry Line {line_num}: {entry.instance_id}")

            except ValueError as e:
                error_msg = f"Line {line_num}: Validation error - {str(e)}"
                result = ValidationResult(line_number=line_num, instance_id=entry.instance_id, success=False, error_message=error_msg)
                validateion_summary.append(result)
                logger.error(f"[ERROR] {error_msg}")

            except Exception as e:
                error_msg = f"Line {line_num}: Unexpected error - {str(e)}"
                result = ValidationResult(line_number=line_num, instance_id=entry.instance_id, success=False, error_message=error_msg)
                validateion_summary.append(result)
                logger.error(f"[ERROR] {error_msg}")

    except FileNotFoundError as e:
        logger.error(f"File not found: {str(e)}")
        raise typer.Exit(code=1)

    except Exception as e:
        logger.error(f"Unexpected error reading dataset: {str(e)}")
        raise typer.Exit(code=1)

    logger.info(f"Total entries processed: {len(validateion_summary)}")
    logger.info(f"Successful validations: {len([r for r in validateion_summary if r.success])}")
    logger.info(f"Failed validations: {len([r for r in validateion_summary if not r.success])}")

    if len([r for r in validateion_summary if not r.success]) > 0:
        logger.error("ERROR DETAILS:")
        for error in [r for r in validateion_summary if not r.success]:
            logger.error(f"  - {error}")

        logger.error("Dataset validation failed.")
        raise typer.Exit(code=1)
    else:
        logger.info(f"Dataset validation successful: All {len(validateion_summary)} entries are valid")
