from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bcbench.dataset.base import BaseDatasetEntry, EntryMetadata

__all__ = ["DatasetEntry", "EntryMetadata", "TestEntry"]


class TestEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    codeunitID: int
    functionName: Annotated[frozenset[str], Field(min_length=1)]


class DatasetEntry(BaseDatasetEntry):
    """Dataset entry for bug-fix and test-generation categories.

    Extends BaseDatasetEntry with test and patch fields shared by both categories.
    """

    fail_to_pass: Annotated[list[TestEntry], Field(alias="FAIL_TO_PASS", min_length=1)]
    pass_to_pass: Annotated[list[TestEntry], Field(alias="PASS_TO_PASS", default_factory=list)]
    test_patch: Annotated[str, Field(min_length=1)]
    patch: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def validate_baseapp_patches_are_w1_only(self) -> DatasetEntry:
        """Validate that patches only modify files in the expected layer (currently W1).

        Only applicable to BaseApp, patches should only modify W1 layer files, not country-specific layers (IT, DE, etc.).
        """
        if self.extract_project_name() != "BaseApp":
            return self

        # Check both patch and test_patch
        for patch in (self.patch, self.test_patch):
            patch_paths = re.findall(r"^diff --git a/(.+?) b/", patch, re.MULTILINE)

            for patch_path in patch_paths:
                match = re.match(r"App/Layers/([^/]+)/", patch_path)
                if match:
                    layer = match.group(1)
                    if layer != "W1":
                        raise ValueError(f"Patch modifies non-W1 layer '{layer}': {patch_path}")

        return self
