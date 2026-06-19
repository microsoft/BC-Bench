"""Evaluation module for running pipelines and creating results."""

from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.evaluate.testgeneration import TestGenerationPipeline

__all__ = ["BugFixPipeline", "EvaluationPipeline", "NL2ALPipeline", "TestGenerationPipeline"]
