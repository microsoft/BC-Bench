from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, TypedDict

from bcbench.logger import get_logger
from bcbench.operations import extract_patches
from bcbench.utils import (
    NAV_REPO_PATH,
    find_project_paths_from_patch,
    strip_html,
)

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
        return cls(
            repo=str(payload.get("repo", "microsoftInternal/NAV")),
            instance_id=str(payload.get("instance_id", "")),
            patch=str(payload.get("patch", "")),
            base_commit=str(payload.get("base_commit", "")),
            hints_text=str(payload.get("hints_text", "")),
            created_at=str(payload.get("created_at", "")),
            test_patch=str(payload.get("test_patch", "")),
            problem_statement=str(payload.get("problem_statement", "")),
            environment_setup_version=str(payload.get("environment_setup_version", "")),
            fail_to_pass=_parse_test_entries(payload.get("FAIL_TO_PASS", [])),
            pass_to_pass=_parse_test_entries(payload.get("PASS_TO_PASS", [])),
            project_paths=_ensure_list_of_str(payload.get("project_paths", [])),
        )

    @classmethod
    def from_ado(
        cls,
        *,
        pr_number: int,
        repo_path: Path,
        pr_data: dict[str, Any],
        work_item_data: dict[str, Any],
        base_commit: str,
        commit: str,
        diff_path: str = "",
    ) -> DatasetEntry:
        """Construct a dataset entry from Azure DevOps artifacts."""
        created_at = _extract_creation_date(pr_data)
        patch, patch_fix, patch_test = extract_patches(repo_path, base_commit, commit, diff_path=diff_path)
        problem_statement = _extract_problem_statement(work_item_data)
        hints = ""  # TODO: Extract hints if available, no instance found yet
        version = _determine_environment_setup_version(commit)

        return cls(
            instance_id=f"microsoftInternal__NAV-{pr_number}",
            base_commit=base_commit,
            commit=commit,
            pr_number=pr_number,
            created_at=created_at,
            patch=patch_fix,
            environment_setup_version=version,
            test_patch=patch_test,
            problem_statement=problem_statement,
            hints_text=hints,
            project_paths=find_project_paths_from_patch(repo_path, patch),
            _raw_pr_data=pr_data,
            _raw_work_item_data=work_item_data,
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


def _determine_environment_setup_version(commit: str) -> str:
    """Determine the appropriate environment setup version based on commit availability in release branches."""

    result = subprocess.run(
        ["git", "show", "master:Directory.App.Props.json"],
        cwd=NAV_REPO_PATH,
        capture_output=True,
        text=True,
        check=True,
    )
    props_data = json.loads(result.stdout)
    current_version_str = props_data["variables"]["app_currentVersion"]
    # Extract major version (e.g., "28.0.0.0" -> 28)
    current_major_version = int(current_version_str.split(".")[0])

    # Start checking from (current_version - 1)
    start_version = current_major_version - 1

    # Check release branches backwards
    for major_version in range(start_version, 20, -1):  # Go back to version 20
        for minor_version in [5, 4, 3, 2, 1, 0]:
            branch_name = f"releases/{major_version}.{minor_version}"

            # Check if branch exists
            branch_check = subprocess.run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/remotes/origin/{branch_name}",
                ],
                cwd=NAV_REPO_PATH,
                capture_output=True,
            )

            if branch_check.returncode == 0:  # Branch exists
                commit_check = subprocess.run(
                    [
                        "git",
                        "merge-base",
                        "--is-ancestor",
                        commit,
                        f"origin/{branch_name}",
                    ],
                    cwd=NAV_REPO_PATH,
                    capture_output=True,
                )

                if commit_check.returncode != 0:  # Commit doesn't exist in this branch
                    return f"{major_version}.{minor_version}"

    return ""


def _ensure_list_of_str(values: Iterable[Any]) -> list[str]:
    return [str(value) for value in values]


def _parse_test_entries(values: Any) -> list[TestEntry]:
    """Parse test entries from JSON payload."""
    if not values:
        return []

    result: list[TestEntry] = []
    for entry in values:
        if isinstance(entry, dict):
            result.append(
                TestEntry(
                    codeunitID=int(entry.get("codeunitID", 0)),
                    functionName=[str(fn) for fn in entry.get("functionName", [])],
                )
            )
        else:
            raise ValueError(f"Invalid test entry format: {entry}")

    return result


def _extract_creation_date(pr_data: dict[str, Any]) -> str:
    creation_date = pr_data.get("creationDate", "")
    if creation_date:
        return creation_date[:10]
    raise ValueError("Creation date not found in PR data.")


def _extract_problem_statement(work_item_data: dict[str, Any]) -> str:
    logger = get_logger(__name__)
    fields = work_item_data.get("fields", {})
    if fields.get("System.CommentCount", 0) > 0:
        logger.warning("Work item has comments, additional handling may be required.")

    repro_steps = strip_html(fields.get("Microsoft.VSTS.TCM.ReproSteps", ""))
    description = strip_html(fields.get("System.Description", ""))

    return f"Title: {fields.get('System.Title', '')}\nRepro Steps:\n{repro_steps}\nDescription:\n{description}\n"
