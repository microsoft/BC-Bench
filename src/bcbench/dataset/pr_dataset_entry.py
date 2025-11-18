"""Representation of PR dataset entries for security review tasks."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

__all__ = ["PRDatasetEntry", "TargetComment", "load_pr_dataset_entries"]


class TargetComment(TypedDict):
    """Target comment that AI agent should generate."""

    comment: str
    line: int


@dataclass(slots=True)
class PRDatasetEntry:
    """Representation of a PR dataset entry for security review."""

    name: str = ""
    description: str = ""
    diff: str = ""
    target_comments: list[TargetComment] = field(default_factory=list)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> PRDatasetEntry:
        """Build an entry from a JSON payload."""
        target_comments = []
        for comment_data in payload.get("target_comments", []):
            target_comments.append(
                TargetComment(
                    comment=str(comment_data.get("comment", "")),
                    line=int(comment_data.get("line", 0)),
                )
            )

        return cls(
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            diff=str(payload.get("diff", "")),
            target_comments=target_comments,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the dataset entry as a dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "diff": self.diff,
            "target_comments": list(self.target_comments),
        }


def load_pr_dataset_entries(dataset_path: Path | str) -> list[PRDatasetEntry]:
    """Load PR dataset entries from a JSONL file.

    Args:
        dataset_path: Path to the prdataset.jsonl file

    Returns:
        List of PRDatasetEntry objects
    """
    path = Path(dataset_path)
    entries = []

    if not path.exists():
        return entries

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                entries.append(PRDatasetEntry.from_json(data))
            except json.JSONDecodeError as e:
                raise ValueError(f"Failed to parse JSON line in {path}: {e}") from e

    return entries
