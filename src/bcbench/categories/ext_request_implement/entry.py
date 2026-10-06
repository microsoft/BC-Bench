from __future__ import annotations

from typing import Annotated, override

from pydantic import Field

from bcbench.dataset.dataset_entry import RepoGroundedEntry
from bcbench.types import Checklist, ChecklistAssertion


class ExtRequestImplementEntry(RepoGroundedEntry):
    """Dataset entry for the extensibility-request-implement category — implement an approved extensibility request in AL.

    Judge-based (no build, no tests). The agent reads the extensibility request (provided as plain
    text) and adds the requested extension point (typically an integration event) to the existing repo
    checked out at `base_commit`. The agent's diff is graded by an LLM judge against `expected`, which
    encodes both fidelity to the gold fix (`patch`) and correct propagation across the expected
    W1 + country/region layer files.
    """

    # LLM-judge checklist: expected event/signature/placement and expected layer propagation.
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]

    @override
    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}
