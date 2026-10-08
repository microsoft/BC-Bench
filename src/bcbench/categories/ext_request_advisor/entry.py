from __future__ import annotations

from typing import Annotated, override

from pydantic import Field

from bcbench.dataset.dataset_entry import RepoGroundedEntry
from bcbench.types import Checklist, ChecklistAssertion


class ExtRequestAdvisorEntry(RepoGroundedEntry):
    """Single-shot proxy for preparing a Business Central extensibility request."""

    patch: str | None = None

    title: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    comments: str = ""
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]

    @override
    def get_task(self) -> str:
        sections = [f"# {self.title}", "", self.description.rstrip()]
        if self.comments.strip():
            sections += ["", "## Additional requester context", "", self.comments.rstrip()]
        return "\n".join(sections)

    @override
    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}
