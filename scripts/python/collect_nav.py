#!/usr/bin/env python3
"""
BC Bench Collect Nav Script

Collect dataset metadata for a NAV pull request from Azure DevOps.
This script replaces the collect_nav command from the CLI package.

Usage:
    python collect_nav.py <pr_number> [options]

Arguments:
    pr_number: Pull request number to collect

Options:
    --output PATH: Output file for the dataset entry (default: c:\\depot\\BC-Bench\\dataset\\bcbench_nav.jsonl)
    --append: Append the dataset entry to the output file instead of overwriting it
    --skip-validate: Skip schema validation before writing the dataset entry
    --verbose: Increase logging verbosity
    --help: Show this help message

Environment Variables:
    ADO_TOKEN: Required Azure DevOps personal access token

Example:
    python collect_nav.py 210528
"""

import argparse
import base64
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict

import requests
from dotenv import load_dotenv

# Import local modules
from dataset_entry import DatasetEntry
from utils import DATASET_PATH

# Set up logging
LOGGER = logging.getLogger(__name__)

# Azure DevOps API base URL
BASE_URL = "https://dev.azure.com/dynamicssmb2/Dynamics%20SMB/_apis/git/repositories/NAV"

# Load environment variables
load_dotenv()


def main() -> int:
    """Main entry point for the collect_nav script."""
    parser = create_parser()
    args = parser.parse_args()

    # Check for required environment variables
    try:
        _validate_environment()
    except ValueError as exc:
        LOGGER.error(str(exc))
        return 1

    # Collect the dataset entry
    try:
        entry = collect_dataset_entry(args.pr_number)
    except Exception as exc:  # pragma: no cover - network interaction
        LOGGER.error("Failed to collect dataset entry: %s", exc)
        return 1

    # Validate the entry if requested
    if not args.skip_validate:
        try:
            entry.validate()
        except ValueError as exc:
            LOGGER.error("Dataset entry validation failed: %s", exc)
            return 1

    # Save the entry to file
    try:
        entry.save_to_file(args.output, append=args.append)
    except OSError as exc:
        LOGGER.error("Failed to write dataset entry: %s", exc)
        return 1

    LOGGER.info("Saved dataset entry to %s", args.output)
    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser."""
    parser = argparse.ArgumentParser(
        description="Collect dataset metadata for a NAV pull request from Azure DevOps.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('\\n\\n', 1)[1] if __doc__ and '\\n\\n' in __doc__ else ""
    )

    parser.add_argument(
        "pr_number",
        type=int,
        help="Pull request number to collect"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATASET_PATH,
        help=f"Output file for the dataset entry (default: {DATASET_PATH})"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append the dataset entry to the output file instead of overwriting it"
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip schema validation before writing the dataset entry"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Increase logging verbosity"
    )

    return parser


def _validate_environment() -> None:
    """Validate that required environment variables are set."""
    if not os.getenv("ADO_TOKEN"):
        raise ValueError("ADO_TOKEN environment variable is required")


def _get_token() -> str:
    """Get the Azure DevOps token from environment."""
    token = os.getenv("ADO_TOKEN")
    if not token:
        raise ValueError("ADO_TOKEN environment variable is required")
    return token


def _get_headers() -> Dict[str, str]:
    """Get headers for Azure DevOps API requests."""
    token = _get_token()
    token_bytes = f":{token}".encode("ascii")
    token_b64 = base64.b64encode(token_bytes).decode("ascii")
    return {
        "Authorization": f"Basic {token_b64}",
        "Content-Type": "application/json",
    }


def _make_ado_git_request(endpoint: str) -> Dict[str, Any]:
    """Make a request to the Azure DevOps Git API."""
    url = f"{BASE_URL}/{endpoint}"
    response = requests.get(url, headers=_get_headers())
    response.raise_for_status()
    return response.json()


def get_pr_info(pr_number: int) -> Dict[str, Any]:
    """Get pull request information from Azure DevOps."""
    endpoint = f"pullrequests/{pr_number}?api-version=7.1"
    return _make_ado_git_request(endpoint)


def get_commit_info(commit: str) -> Dict[str, Any]:
    """Get commit information from Azure DevOps."""
    endpoint = f"commits/{commit}?api-version=7.1"
    return _make_ado_git_request(endpoint)


def get_work_item_info(pr_data: Dict[str, Any]) -> Dict[str, Any]:
    """Get work item information linked to the pull request."""
    work_items = pr_data.get("_links", {}).get("workItems")
    if not work_items or len(work_items) != 1:
        raise ValueError("PR should be linked to exactly one work item.")

    work_item_url = work_items[0]["href"] if isinstance(work_items, list) else work_items.get("href", "")
    if not work_item_url:
        raise ValueError("Unable to determine work item URL from PR data.")

    response = requests.get(work_item_url, headers=_get_headers())
    response.raise_for_status()
    work_item_ref = response.json()

    if work_item_ref.get("count") == 1:
        work_item_url = work_item_ref["value"][0]["url"]
        response = requests.get(work_item_url, headers=_get_headers())
        response.raise_for_status()
        return response.json()

    raise ValueError("Work item reference count is not 1.")


def collect_dataset_entry(pr_number: int) -> DatasetEntry:
    """Collect dataset entry for the given pull request number."""
    LOGGER.info("Collecting dataset entry for PR #%s", pr_number)

    pr_data = get_pr_info(pr_number)
    work_item_data = get_work_item_info(pr_data)

    commit_id = pr_data["lastMergeSourceCommit"]["commitId"]
    commit_data = get_commit_info(commit_id)
    parents = commit_data.get("parents", [])
    if len(parents) != 1:
        raise ValueError("Commit has multiple parents, cannot determine base commit.")

    base_commit = parents[0]

    return DatasetEntry.from_ado(
        pr_number=pr_number,
        pr_data=pr_data,
        work_item_data=work_item_data,
        base_commit=base_commit,
        commit=commit_id,
    )


def get_dataset_from_pr(pr_number: int) -> DatasetEntry:
    """Backward compatible alias for collect_dataset_entry."""
    return collect_dataset_entry(pr_number)


if __name__ == "__main__":
    sys.exit(main())