from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from bcbench_core.registry import CategoryRegistry

if TYPE_CHECKING:
    from bcbench.categories.base import CategoryDefinition


def _load(module: str) -> CategoryDefinition:
    from bcbench.categories.base import CategoryDefinition

    definition = import_module(f"bcbench.categories.{module}").DEFINITION
    if not isinstance(definition, CategoryDefinition):
        raise TypeError(f"{module} must export a CategoryDefinition")
    return definition


categories = CategoryRegistry(
    (
        ("bug-fix", lambda: _load("bugfix")),
        ("test-generation", lambda: _load("testgeneration")),
        ("code-review", lambda: _load("codereview")),
        ("nl2al", lambda: _load("nl2al")),
        ("data-query", lambda: _load("dataquery")),
        ("extensibility-request-advisor", lambda: _load("ext_request_advisor")),
        ("extensibility-request-implement", lambda: _load("ext_request_implement")),
        ("extensibility-request-triage", lambda: _load("ext_request_triage")),
    )
)
