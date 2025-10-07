"""Dataset query operations for CLI commands."""

import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Set

import typer

from bcbench.core.dataset_entry import DatasetEntry

__all__ = ["query_versions", "query_entries", "query_entry_matrix"]

logger = logging.getLogger(__name__)


def _get_unique_versions(dataset_path: Path) -> List[str]:
    """
    Extract unique environment setup versions from the dataset.

    Args:
        dataset_path: Path to the bcbench_nav.jsonl dataset file

    Returns:
        List of unique environment setup versions, sorted

    Raises:
        FileNotFoundError: If the dataset file doesn't exist
        ValueError: If there's an error reading or parsing the dataset
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    versions: Set[str] = set()

    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
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
                    logger.warning(f"Invalid JSON on line {line_num}: {e}")
                except Exception as e:
                    logger.warning(f"Error processing line {line_num}: {e}")

    except Exception as e:
        raise ValueError(f"Failed to read dataset file: {e}") from e

    # Return sorted list for consistent ordering
    return sorted(versions)


def _get_entries_for_version(version: str, dataset_path: Path) -> List[str]:
    """
    Get instance IDs for all entries with a specific environment setup version.

    Args:
        version: The environment setup version to filter by
        dataset_path: Path to the bcbench_nav.jsonl dataset file

    Returns:
        List of instance IDs matching the version

    Raises:
        FileNotFoundError: If the dataset file doesn't exist
    """
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    instance_ids: List[str] = []

    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
                entry = DatasetEntry.from_json(data)
                if entry.environment_setup_version == version:
                    instance_ids.append(entry.instance_id)
            except Exception as e:
                logger.debug(f"Skipping invalid entry: {e}")
                continue

    return instance_ids


def query_versions(
    dataset_path: Path,
    github_output: Optional[str] = None,
) -> List[str]:
    """
    Get unique environment setup versions from the dataset.

    Args:
        dataset_path: Path to the dataset file
        github_output: If provided, write to GITHUB_OUTPUT with this key name

    Returns:
        List of unique versions

    Raises:
        typer.Exit: Exits with code 1 on failure
    """
    try:
        versions = _get_unique_versions(dataset_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise typer.Exit(code=1)
    except ValueError as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

    if not versions:
        logger.error("No versions found in dataset")
        raise typer.Exit(code=1)

    # Display results to user
    print(f"Found {len(versions)} unique version(s):")
    for version in versions:
        print(f"  - {version}")

    # Write to GitHub Actions output if requested
    if github_output:
        _write_github_output(github_output, json.dumps(versions))
        logger.info(f"Written to GITHUB_OUTPUT as '{github_output}'")

    return versions


def query_entries(
    version: str,
    dataset_path: Path,
    github_output: Optional[str] = None,
) -> List[str]:
    """
    Get all instance IDs for a specific environment setup version.

    Args:
        version: The version to filter by
        dataset_path: Path to the dataset file
        github_output: If provided, write to GITHUB_OUTPUT with this key name

    Returns:
        List of instance IDs

    Raises:
        typer.Exit: Exits with code 1 on failure
    """
    try:
        entries = _get_entries_for_version(version, dataset_path)
    except FileNotFoundError as e:
        logger.error(str(e))
        raise typer.Exit(code=1)

    if not entries:
        logger.error(f"No entries found for version: {version}")
        raise typer.Exit(code=1)

    print(f"Found {len(entries)} entry(ies) for version {version}:")
    for entry_id in entries:
        print(f"  - {entry_id}")

    if github_output:
        _write_github_output(github_output, json.dumps(entries))
        logger.info(f"Written to GITHUB_OUTPUT as '{github_output}'")

    return entries


def query_entry_matrix(
    dataset_path: Path,
    github_output: Optional[str] = None,
) -> List[dict]:
    """
    Get all entries with their version information for GitHub Actions matrix.

    Args:
        dataset_path: Path to the dataset file
        github_output: If provided, write to GITHUB_OUTPUT with this key name

    Returns:
        List of dictionaries with 'entry' and 'version' keys

    Raises:
        typer.Exit: Exits with code 1 on failure
    """
    if not dataset_path.exists():
        logger.error(f"Dataset file not found: {dataset_path}")
        raise typer.Exit(code=1)

    entry_matrix: List[dict] = []

    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    entry = DatasetEntry.from_json(data)
                    if entry.instance_id and entry.environment_setup_version:
                        entry_matrix.append({"entry": entry.instance_id, "version": entry.environment_setup_version})
                except Exception as e:
                    logger.debug(f"Skipping invalid entry: {e}")
                    continue
    except Exception as e:
        logger.error(f"Failed to read dataset file: {e}")
        raise typer.Exit(code=1)

    if not entry_matrix:
        logger.error("No valid entries found in dataset")
        raise typer.Exit(code=1)

    print(f"Found {len(entry_matrix)} entry(ies) for evaluation:")
    for item in entry_matrix:
        print(f"  - {item['entry']} (version: {item['version']})")

    if github_output:
        _write_github_output(github_output, json.dumps(entry_matrix))
        logger.info(f"Written to GITHUB_OUTPUT as '{github_output}'")

    return entry_matrix


def _write_github_output(name: str, value: str) -> None:
    """
    Write a value to GitHub Actions output.

    Args:
        name: The output variable name
        value: The output value

    Raises:
        typer.Exit: Exits with code 1 if GITHUB_OUTPUT is not set or write fails
    """
    github_output_file = os.environ.get("GITHUB_OUTPUT")
    if not github_output_file:
        logger.error("GITHUB_OUTPUT environment variable not set")
        raise typer.Exit(code=1)

    try:
        with open(github_output_file, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")
    except Exception as e:
        logger.error(f"Failed to write to GITHUB_OUTPUT: {e}")
        raise typer.Exit(code=1)
