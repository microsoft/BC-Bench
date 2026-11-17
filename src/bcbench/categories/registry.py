"""Looks up the definition of each evaluation category."""

from typing import Any

from bcbench.categories.data_query import DEFINITION as DATA_QUERY
from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_advisor import DEFINITION as EXT_REQUEST_ADVISOR
from bcbench.categories.ext_request_implement import DEFINITION as EXT_REQUEST_IMPLEMENT
from bcbench.categories.ext_request_triage import DEFINITION as EXT_REQUEST_TRIAGE
from bcbench.types import EvaluationCategory

__all__ = ["category_definition"]


def category_definition(category: EvaluationCategory) -> CategoryDefinition[Any] | None:
    """The CLI selects categories at runtime, so the entry type is only known inside each definition.

    Returns None for categories still served by `EvaluationCategory` and `EvaluationPipeline` (transitional: becomes exhaustive once all are migrated).
    """
    match category:
        case EvaluationCategory.DATA_QUERY:
            return DATA_QUERY
        case EvaluationCategory.EXT_REQUEST_ADVISOR:
            return EXT_REQUEST_ADVISOR
        case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
            return EXT_REQUEST_IMPLEMENT
        case EvaluationCategory.EXT_REQUEST_TRIAGE:
            return EXT_REQUEST_TRIAGE
        case _:
            return None
