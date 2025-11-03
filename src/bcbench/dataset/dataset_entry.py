from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, TypedDict

from bcbench.exceptions import InvalidEntryFormatError

__all__ = ["DatasetEntry"]


class TestEntry(TypedDict):
    codeunitID: int
    functionName: list[str]


@dataclass(slots=True)
class DatasetEntry:
    """Representation of a Business Central benchmark dataset entry."""

    repo: str = "microsoftInternal/NAV"
    instance_id: str = ""
    patch: str = ""
    base_commit: str = ""
    hints_text: str = ""
    created_at: str = ""
    test_patch: str = ""
    problem_statement: str = ""
    environment_setup_version: str = ""
    fail_to_pass: list[TestEntry] = field(default_factory=list)
    pass_to_pass: list[TestEntry] = field(default_factory=list)
    project_paths: list[str] = field(default_factory=list)
    commit: str = ""
    pr_number: int | None = None
    _raw_pr_data: dict[str, Any] | None = field(default=None, repr=False)
    _raw_work_item_data: dict[str, Any] | None = field(default=None, repr=False)

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> DatasetEntry:
        """Build an entry from a JSON payload stored in the dataset file."""
        instance_id = str(payload.get("instance_id", ""))
        return cls(
            repo=str(payload.get("repo", "microsoftInternal/NAV")),
            instance_id=instance_id,
            patch=str(payload.get("patch", "")),
            base_commit=str(payload.get("base_commit", "")),
            hints_text=str(payload.get("hints_text", "")),
            created_at=str(payload.get("created_at", "")),
            test_patch=str(payload.get("test_patch", "")),
            problem_statement=str(payload.get("problem_statement", "")),
            environment_setup_version=str(payload.get("environment_setup_version", "")),
            fail_to_pass=_parse_test_entries(instance_id, payload.get("FAIL_TO_PASS", [])),
            pass_to_pass=_parse_test_entries(instance_id, payload.get("PASS_TO_PASS", [])),
            project_paths=_ensure_list_of_str(payload.get("project_paths", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the dataset entry as a dictionary matching the schema."""
        return {
            "repo": self.repo,
            "instance_id": self.instance_id,
            "base_commit": self.base_commit,
            "created_at": self.created_at,
            "environment_setup_version": self.environment_setup_version,
            "project_paths": list(self.project_paths),
            "hints_text": self.hints_text,
            "FAIL_TO_PASS": list(self.fail_to_pass),
            "PASS_TO_PASS": list(self.pass_to_pass),
            "problem_statement": self.problem_statement,
            "test_patch": self.test_patch,
            "patch": self.patch,
        }

    def save_to_file(self, filepath: Path | str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            # For JSONL format, always write compact JSON without indentation
            json.dump(self.to_dict(), handle, ensure_ascii=False)
            handle.write("\n")

    def get_task(self) -> str:
        """Get the full task description including hints."""
        task = self.problem_statement
        if self.hints_text:
            task += f"\n\n## Additional Hints\n{self.hints_text}"
        return task


def _ensure_list_of_str(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values]


def _parse_test_entries(instance_id: str, values: Any) -> list[TestEntry]:
    """Parse test entries from JSON payload."""
    if not values:
        return []

    result: list[TestEntry] = []
    for test_entry in values:
        try:
            result.append(
                TestEntry(
                    codeunitID=int(test_entry.get("codeunitID")),
                    functionName=[str(fn) for fn in test_entry.get("functionName")],
                )
            )
        except Exception as e:
            raise InvalidEntryFormatError(instance_id, f"Expected dict with codeunitID and functionName: {e}") from None

    return result
