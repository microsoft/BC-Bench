import base64
import os
from pathlib import Path
from typing import Any, Dict

import requests
import typer
from dotenv import load_dotenv

from bcbench.dataset.dataset_entry import DatasetEntry
from bcbench.core.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://dev.azure.com/dynamicssmb2/Dynamics%20SMB/_apis/git/repositories/NAV"

load_dotenv()


def collect_nav_entry(
    pr_number: int,
    output: Path,
    overwrite: bool = False,
    diff_path: str = "",
) -> None:
    try:
        _validate_environment()
    except ValueError as exc:
        logger.error(str(exc))
        raise typer.Exit(code=1)

    try:
        entry: DatasetEntry = collect_dataset_entry(pr_number, diff_path=diff_path)
    except Exception as exc:
        logger.error("Failed to collect dataset entry: %s", exc)
        raise typer.Exit(code=1)

    try:
        entry.save_to_file(output, overwrite=overwrite)
    except OSError as exc:
        logger.error("Failed to write dataset entry: %s", exc)
        raise typer.Exit(code=1)

    logger.info(f"Saved dataset entry {entry.instance_id} to {output}")


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
    elif work_item_ref.get("count", 0) > 1:
        logger.info("Multiple work items found. Please select one:")
        for idx, item in enumerate(work_item_ref["value"], 1):
            logger.info(f"{idx}. Work Item #{item.get('id')} - {item.get('url')}")

        choice: int = typer.prompt("Enter the number of the work item to use", type=int)
        if choice < 1 or choice > len(work_item_ref["value"]):
            raise ValueError("Invalid selection.")

        work_item_url = work_item_ref["value"][choice - 1]["url"]
        response = requests.get(work_item_url, headers=_get_headers())
        response.raise_for_status()
        return response.json()

    raise ValueError("No work items found in the reference.")


def collect_dataset_entry(pr_number: int, diff_path: str = "") -> DatasetEntry:
    """Collect dataset entry for the given pull request number."""
    logger.info("Collecting dataset entry for PR #%s", pr_number)

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
        diff_path=diff_path,
    )


def get_dataset_from_pr(pr_number: int) -> DatasetEntry:
    """Backward compatible alias for collect_dataset_entry."""
    return collect_dataset_entry(pr_number)
