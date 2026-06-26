"""Evaluation module for running pipelines and creating results."""

from bcbench.evaluate.base import EvaluationPipeline
from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.evaluate.codereview import CodeReviewPipeline
from bcbench.evaluate.hello_world import HelloWorldPipeline
from bcbench.evaluate.nl2al import NL2ALPipeline
from bcbench.evaluate.testgeneration import TestGenerationPipeline

__all__ = ["BugFixPipeline", "CodeReviewPipeline", "EvaluationPipeline", "HelloWorldPipeline", "NL2ALPipeline", "TestGenerationPipeline"]
