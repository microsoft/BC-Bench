"""Azure DevOps API client for fetching PR and work item data."""

import base64
from typing import Any

import requests
import typer

from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)

BASE_URL = "https://dev.azure.com/dynamicssmb2/Dynamics%20SMB/_apis/git/repositories/NAV"


class ADOClient:
    def __init__(self, token: str):
        self.token = token

    def get_pr_info(self, pr_number: int) -> dict[str, Any]:
        endpoint = f"pullrequests/{pr_number}?api-version=7.1"
        return self._make_request(endpoint)

    def get_commit_info(self, commit: str) -> dict[str, Any]:
        endpoint = f"commits/{commit}?api-version=7.1"
        return self._make_request(endpoint)

    def get_work_item_info(self, pr_data: dict[str, Any]) -> dict[str, Any]:
        work_items = pr_data.get("_links", {}).get("workItems")
        if not work_items or len(work_items) != 1:
            raise CollectionError("PR should be linked to exactly one work item.")

        work_item_url = work_items[0]["href"] if isinstance(work_items, list) else work_items.get("href", "")
        if not work_item_url:
            raise CollectionError("Unable to determine work item URL from PR data.")

        response = requests.get(work_item_url, headers=self._get_headers())
        response.raise_for_status()
        work_item_ref = response.json()

        if work_item_ref.get("count") == 1:
            work_item_url = work_item_ref["value"][0]["url"]
            response = requests.get(work_item_url, headers=self._get_headers())
            response.raise_for_status()
            return response.json()

        if work_item_ref.get("count", 0) > 1:
            logger.info("Multiple work items found. Please select one:")
            for idx, item in enumerate(work_item_ref["value"], 1):
                logger.info(f"{idx}. Work Item #{item.get('id')} - {item.get('url')}")

            choice: int = typer.prompt("Enter the number of the work item to use", type=int)
            if choice < 1 or choice > len(work_item_ref["value"]):
                raise CollectionError("Invalid selection.")

            work_item_url = work_item_ref["value"][choice - 1]["url"]
            response = requests.get(work_item_url, headers=self._get_headers())
            response.raise_for_status()
            return response.json()

        raise CollectionError("No work items found in the reference.")

    def _make_request(self, endpoint: str) -> dict[str, Any]:
        url = f"{BASE_URL}/{endpoint}"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def _get_headers(self) -> dict[str, str]:
        token_bytes: bytes = f":{self.token}".encode("ascii")
        token_b64: str = base64.b64encode(token_bytes).decode("ascii")
        return {
            "Authorization": f"Basic {token_b64}",
            "Content-Type": "application/json",
        }
