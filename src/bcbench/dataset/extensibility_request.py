from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from bcbench.dataset.dataset_entry import RepoGroundedEntry
from bcbench.types import Checklist, ChecklistAssertion

__all__ = ["ExtRequestImplementEntry", "ExtRequestTriageEntry", "ManagedLabel"]


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

    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}


type ManagedLabel = Literal[
    "Finance",
    "SCM",
    "Integration",
    "event-request",
    "request-for-external",
    "enum-request",
    "extensibility-enhancement",
    "missing-info",
    "agent-not-processable",
]


class ExtRequestTriageEntry(RepoGroundedEntry):
    """Dataset entry for the extensibility-request-triage category — triage a single extensibility request.

    Judge-based (no build, no tests), scored by LMChecklist like NL2AL and extensibility-request-implement.
    The agent reads one extensibility-request thread (rendered from `title` + `description` + any follow-up
    `comments`, plus `current_labels` already on the request) and analyses feasibility against the standard
    AL source checked out at `base_commit`. It writes its `Final_Output` triage decision — the managed labels
    to set, an advisory comment, and whether the request stays open or is closed. That raw decision is scored
    downstream by an LLM judge against `expected`, a checklist encoding the correct labels, issue state and the
    substance of the advisory comment.
    """

    # Triage has no gold code diff; the expected answer lives in the `expected` checklist below.
    patch: str | None = None

    title: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    comments: str = ""
    current_labels: Annotated[list[ManagedLabel], Field(default_factory=list)]

    # LLM-judge checklist: expected labels_to_set, issue_state and advisory-comment substance.
    expected: Annotated[list[ChecklistAssertion], Field(min_length=1)]

    def get_task(self) -> str:
        sections = [f"# {self.title}", "", self.description.rstrip()]
        if self.current_labels:
            sections += ["", f"Current labels: {', '.join(self.current_labels)}"]
        if self.comments.strip():
            sections += ["", "## Follow-up conversation", "", self.comments.rstrip()]
        return "\n".join(sections)

    def get_expected_output(self) -> Checklist:
        return {"assertions": self.expected}
