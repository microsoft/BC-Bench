"""Evaluation module for running pipelines and creating results."""

from bcbench.evaluate.base import EvaluationPipeline, create_pipeline
from bcbench.evaluate.testgeneration import setup_repo

__all__ = ["EvaluationPipeline", "create_pipeline", "setup_repo"]
