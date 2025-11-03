"""Validate all entries in the BC-Bench dataset against the JSON schema."""

import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import SchemaError, ValidationError, validate

from bcbench.dataset.dataset_loader import load_dataset_entries
from bcbench.logger import get_logger

logger = get_logger(__name__)
__all__ = ["ValidationResult", "validate_entries"]


@dataclass
class ValidationResult:
    """Structure to hold validation results for a single entry."""

    line_number: int
    instance_id: str
    success: bool
    error_message: str | None = None


def validate_entries(dataset_path: Path, schema_path: Path) -> list[ValidationResult]:
    """
    Validate all dataset entries against a JSON schema.

    Args:
        dataset_path: Path to the dataset file
        schema_path: Path to the JSON schema file

    Returns:
        List of ValidationResult objects
    """
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    entries = load_dataset_entries(dataset_path)
    results: list[ValidationResult] = []

    for line_num, entry in enumerate(entries, 1):
        try:
            validate(instance=entry.to_dict(), schema=schema)
            results.append(ValidationResult(line_number=line_num, instance_id=entry.instance_id, success=True))
        except ValidationError as e:
            error_msg: str = f"Line {line_num}: Validation error - {e!s}"
            logger.error(error_msg)

            results.append(
                ValidationResult(
                    line_number=line_num,
                    instance_id=entry.instance_id,
                    success=False,
                    error_message=error_msg,
                )
            )
        except SchemaError as e:
            logger.error(f"Invalid schema in {schema_path}: {e.message}")
            raise
        except Exception as e:
            error_msg: str = f"Line {line_num}: Unexpected error - {e!s}"
            logger.error(error_msg)

            results.append(
                ValidationResult(
                    line_number=line_num,
                    instance_id=entry.instance_id,
                    success=False,
                    error_message=error_msg,
                )
            )

    return results
