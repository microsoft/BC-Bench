from __future__ import annotations

from typing import Annotated, Literal, override

from pydantic import Field

from bcbench.dataset.dataset_entry import BaseDatasetEntry
from bcbench.types import Checklist, ChecklistAssertion


class NL2ALEntry(BaseDatasetEntry):
    """Dataset entry for NL2AL category — generate AL code from natural language."""

    nl_prompt: Annotated[str, Field(min_length=1, pattern=r"^[^\x00]*$")]
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]
    page: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9 ./]*$")]
    audience: Literal["Business", "Technical", "Both"]

    @property
    @override
    def customization_profile(self) -> str:
        return "nl2al"

    @override
    def get_task(self) -> str:
        return self.nl_prompt

    @override
    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}
