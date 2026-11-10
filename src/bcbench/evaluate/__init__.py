"""Evaluation module for running pipelines and creating results.

Transitional: the pipelines here are replaced by `bcbench.categories` and `bcbench_core.evaluation` as categories migrate.
"""

from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.evaluate.testgeneration import TestGenerationPipeline

__all__ = [
    "BugFixPipeline",
    "CodeReviewPipeline",
    "EvaluationPipeline",
    "NL2ALPipeline",
    "TestGenerationPipeline",
]
