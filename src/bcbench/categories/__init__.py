"""Evaluation categories: each package under bcbench.categories owns one category's definition and behaviour."""

from typing import Any, assert_never

from bcbench.categories.bug_fix.definition import DEFINITION as BUG_FIX
from bcbench.categories.code_review.definition import DEFINITION as CODE_REVIEW
from bcbench.categories.data_query.definition import DEFINITION as DATA_QUERY
from bcbench.categories.definition import CategoryDefinition
from bcbench.categories.ext_request_advisor.definition import DEFINITION as EXT_REQUEST_ADVISOR
from bcbench.categories.ext_request_implement.definition import DEFINITION as EXT_REQUEST_IMPLEMENT
from bcbench.categories.ext_request_triage.definition import DEFINITION as EXT_REQUEST_TRIAGE
from bcbench.categories.nl2al.definition import DEFINITION as NL2AL
from bcbench.categories.test_generation.definition import DEFINITION as TEST_GENERATION
from bcbench.types import EvaluationCategory

__all__ = ["CategoryDefinition", "category_definition"]


def category_definition(category: EvaluationCategory) -> CategoryDefinition[Any]:
    """The CLI selects categories at runtime, so the entry type is only known inside each definition, where it is checked."""
    match category:
        case EvaluationCategory.BUG_FIX:
            return BUG_FIX
        case EvaluationCategory.TEST_GENERATION:
            return TEST_GENERATION
        case EvaluationCategory.CODE_REVIEW:
            return CODE_REVIEW
        case EvaluationCategory.NL2AL:
            return NL2AL
        case EvaluationCategory.DATA_QUERY:
            return DATA_QUERY
        case EvaluationCategory.EXT_REQUEST_ADVISOR:
            return EXT_REQUEST_ADVISOR
        case EvaluationCategory.EXT_REQUEST_IMPLEMENT:
            return EXT_REQUEST_IMPLEMENT
        case EvaluationCategory.EXT_REQUEST_TRIAGE:
            return EXT_REQUEST_TRIAGE
        case _:
            assert_never(category)
