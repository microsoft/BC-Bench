"""Counterfactual dataset entry model.

CF entries are lightweight variants of base bug-fix entries. They share the same
repo state (repo, base_commit, project_paths) but provide a different fix and test pair.
At load time, base entry fields are resolved from bcbench.jsonl.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

from pydantic import Field

from bcbench.config import get_config
from bcbench.dataset.dataset_entry import _BugFixTestGenBase

_config = get_config()

_CF_INSTANCE_PATTERN = r"^[a-zA-Z0-9_-]+__[a-zA-Z0-9_-]+-[0-9]+__cf-[0-9]+$"

__all__ = ["CounterfactualEntry"]


class CounterfactualEntry(_BugFixTestGenBase):
    """Dataset entry for the counterfactual evaluation category.

    Inherits all execution fields from _BugFixTestGenBase (patch, test_patch,
    FAIL_TO_PASS, PASS_TO_PASS) and adds CF-specific metadata.

    At load time, missing fields (repo, base_commit, project_paths, etc.)
    are resolved from the base entry in bcbench.jsonl.
    """

    instance_id: str = Field(pattern=_CF_INSTANCE_PATTERN)

    base_instance_id: str
    variant_description: str = ""
    failure_layer: str | None = None
    problem_statement_override: str | None = None

    @property
    def problem_statement_dir(self) -> Path:
        if self.problem_statement_override:
            return _config.paths.bc_bench_root / self.problem_statement_override
        return _config.paths.problem_statement_dir / self.instance_id

    def get_expected_output(self) -> str:
        return self.patch

    @classmethod
    def load(cls, dataset_path: Path, entry_id: str | None = None, random: int | None = None) -> list[Self]:
        from bcbench.dataset.dataset_entry import BugFixEntry

        base_dataset_path = _config.paths.dataset_dir / "bcbench.jsonl"
        base_entries = {e.instance_id: e for e in BugFixEntry.load(base_dataset_path)}

        raw_entries = _load_raw_entries(dataset_path, entry_id)

        resolved: list[Self] = []
        for raw in raw_entries:
            base = base_entries.get(raw["base_instance_id"])
            if base is None:
                raise ValueError(f"Base entry '{raw['base_instance_id']}' not found for CF entry '{raw['instance_id']}'")

            merged = {
                "repo": base.repo,
                "base_commit": base.base_commit,
                "created_at": base.created_at,
                "environment_setup_version": base.environment_setup_version,
                "project_paths": list(base.project_paths),
                "metadata": base.metadata.model_dump(),
                **raw,
            }
            resolved.append(cls.model_validate(merged))

        if random is not None and random > 0:
            import random as random_module

            return random_module.sample(resolved, min(random, len(resolved)))

        return resolved


def _load_raw_entries(dataset_path: Path, entry_id: str | None) -> list[dict]:
    import json

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    entries: list[dict] = []
    with open(dataset_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            data = json.loads(stripped)
            if entry_id:
                if data["instance_id"] == entry_id:
                    return [data]
                continue
            entries.append(data)

    if entry_id:
        from bcbench.exceptions import EntryNotFoundError

        raise EntryNotFoundError(entry_id)

    return entries
