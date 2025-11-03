from pathlib import Path
from typing import Any

import typer

from bcbench.collection.ado_client import ADOClient
from bcbench.collection.build_entry import build_dataset_entry_from_ado
from bcbench.config import get_config
from bcbench.dataset import DatasetEntry
from bcbench.exceptions import CollectionError
from bcbench.logger import get_logger

logger = get_logger(__name__)


def collect_nav_entry(
    pr_number: int,
    output: Path,
    repo_path: Path,
    diff_path: str = "",
) -> None:
    config = get_config()
    ado_token = config.resolve_ado_token()
    ado_client = ADOClient(ado_token)

    try:
        logger.info("Collecting dataset entry for PR #%s", pr_number)

        pr_data: dict[str, Any] = ado_client.get_pr_info(pr_number)
        work_item_data: dict[str, Any] = ado_client.get_work_item_info(pr_data)

        commit_id: str = pr_data["lastMergeSourceCommit"]["commitId"]
        commit_data: dict[str, Any] = ado_client.get_commit_info(commit_id)
        parents: list[str] = commit_data.get("parents", [])
        if len(parents) != 1:
            raise CollectionError("Commit has multiple parents, cannot determine base commit.")

        entry: DatasetEntry = build_dataset_entry_from_ado(
            pr_number=pr_number,
            repo_path=repo_path,
            pr_data=pr_data,
            work_item_data=work_item_data,
            base_commit=parents[0],
            commit=commit_id,
            diff_path=diff_path,
        )

    except Exception as exc:
        logger.error("Failed to collect dataset entry: %s", exc)
        raise typer.Exit(code=1) from exc

    try:
        entry.save_to_file(output)
    except OSError as exc:
        logger.error("Failed to write dataset entry: %s", exc)
        raise typer.Exit(code=1) from exc

    logger.info(f"Saved dataset entry {entry.instance_id} to {output}")
