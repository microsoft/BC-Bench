"""Evaluation module for running pipelines and creating results."""

from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.evaluate.testgeneration import TestGenerationPipeline

__all__ = ["BugFixPipeline", "EvaluationPipeline", "TestGenerationPipeline"]
