from __future__ import annotations

import json
import re
from abc import abstractmethod
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bcbench.config import get_config
from bcbench.exceptions import EntryNotFoundError

_config = get_config()

__all__ = ["BaseDatasetEntry", "BugFixEntry", "TestEntry", "TestGenEntry"]


class TestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    codeunitID: int
    functionName: Annotated[frozenset[str], Field(min_length=1)]


class EntryMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    area: str | None = None
    image_count: int | None = None


class BaseDatasetEntry(BaseModel):
    """Base class for all dataset entries. Contains common properties shared across categories."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    metadata: EntryMetadata = Field(default_factory=EntryMetadata)

    repo: str = Field(default="microsoft/BCApps", pattern=r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_-]+$")
    instance_id: str = Field(pattern=_config.file_patterns.instance_pattern)
    base_commit: str = Field(pattern=r"^[a-fA-F0-9]{40}$")
    created_at: Annotated[str, Field(min_length=1)]
    environment_setup_version: str = Field(pattern=r"^[0-9]{2}\.[0-9]{1}$")
    project_paths: list[str] = []
    patch: Annotated[str, Field(min_length=1)]

    @classmethod
    def load(cls, dataset_path: Path, entry_id: str | None = None, random: int | None = None) -> list[Self]:
        if not dataset_path.exists():
            raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

        entries: list[Self] = []

        with open(dataset_path, encoding="utf-8") as file:
            for line in file:
                stripped_line: str = line.strip()
                if not stripped_line:
                    continue

                entry = cls.model_validate_json(stripped_line)

                if entry_id:
                    if entry.instance_id == entry_id:
                        return [entry]
                    continue

                entries.append(entry)

        if entry_id:
            raise EntryNotFoundError(entry_id)

        if random is not None and random > 0:
            import random as random_module

            return random_module.sample(entries, min(random, len(entries)))

        return entries

    def save_to_file(self, filepath: Path | str) -> None:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            json.dump(self.model_dump(by_alias=True, mode="json"), handle, ensure_ascii=False)
            handle.write("\n")

    @abstractmethod
    def get_task(self) -> str:
        pass

    @abstractmethod
    def get_expected_output(self) -> str:
        pass

    def extract_project_name(self) -> str:
        if not self.project_paths:
            return ""

        path = self.project_paths[0]
        parts = path.replace("\\", "/").split("/")

        if len(parts) >= 4:
            return parts[-2] if parts[-1].lower() in ("app", "test") else parts[-1]

        return parts[-1] if parts else ""


class _BugFixTestGenBase(BaseDatasetEntry):
    """Shared schema for bug-fix and test-generation entries (same JSONL, different semantics)."""

    fail_to_pass: Annotated[list[TestEntry], Field(alias="FAIL_TO_PASS", min_length=1)]
    pass_to_pass: Annotated[list[TestEntry], Field(alias="PASS_TO_PASS")] = []
    test_patch: Annotated[str, Field(min_length=1)]

    @property
    def problem_statement_dir(self) -> Path:
        return _config.paths.problem_statement_dir / self.instance_id

    def get_task(self) -> str:
        readme_path = self.problem_statement_dir / _config.file_patterns.problem_statement_readme
        return readme_path.read_text(encoding="utf-8")

    @model_validator(mode="after")
    def validate_baseapp_patches_are_w1_only(self) -> Self:
        if self.extract_project_name() != "BaseApp":
            return self

        for patch in (self.patch, self.test_patch):
            patch_paths = re.findall(r"^diff --git a/(.+?) b/", patch, re.MULTILINE)

            for patch_path in patch_paths:
                match = re.match(r"App/Layers/([^/]+)/", patch_path)
                if match:
                    layer = match.group(1)
                    if layer != "W1":
                        raise ValueError(f"Patch modifies non-W1 layer '{layer}': {patch_path}")

        return self


class BugFixEntry(_BugFixTestGenBase):
    """Dataset entry for the bug-fix category."""

    def get_expected_output(self) -> str:
        return self.patch


class TestGenEntry(_BugFixTestGenBase):
    """Dataset entry for the test-generation category."""

    def get_expected_output(self) -> str:
        return self.test_patch
