"""Evaluation module for running pipelines and creating results."""

from importlib import import_module
from typing import TYPE_CHECKING

from bcbench.evaluate.base import AgentRunner, EvaluationPipeline

if TYPE_CHECKING:
    from bcbench.evaluate.bugfix import BugFixPipeline
    from bcbench.evaluate.codereview import CodeReviewPipeline
    from bcbench.evaluate.dataquery import DataQueryPipeline
    from bcbench.evaluate.ext_request_advisor import ExtRequestAdvisorPipeline
    from bcbench.evaluate.ext_request_implement import ExtRequestImplementPipeline
    from bcbench.evaluate.ext_request_triage import ExtRequestTriagePipeline
    from bcbench.evaluate.nl2al import NL2ALPipeline
    from bcbench.evaluate.testgeneration import TestGenerationPipeline

_LAZY_EXPORTS = {
    "BugFixPipeline": "bcbench.evaluate.bugfix",
    "CodeReviewPipeline": "bcbench.evaluate.codereview",
    "DataQueryPipeline": "bcbench.evaluate.dataquery",
    "ExtRequestAdvisorPipeline": "bcbench.evaluate.ext_request_advisor",
    "ExtRequestImplementPipeline": "bcbench.evaluate.ext_request_implement",
    "ExtRequestTriagePipeline": "bcbench.evaluate.ext_request_triage",
    "NL2ALPipeline": "bcbench.evaluate.nl2al",
    "TestGenerationPipeline": "bcbench.evaluate.testgeneration",
}


def __getattr__(name: str) -> object:
    if name in _LAZY_EXPORTS:
        return getattr(import_module(_LAZY_EXPORTS[name]), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentRunner",
    "BugFixPipeline",
    "CodeReviewPipeline",
    "DataQueryPipeline",
    "EvaluationPipeline",
    "ExtRequestAdvisorPipeline",
    "ExtRequestImplementPipeline",
    "ExtRequestTriagePipeline",
    "NL2ALPipeline",
    "TestGenerationPipeline",
]
