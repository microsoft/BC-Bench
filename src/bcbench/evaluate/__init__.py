"""Evaluation module for running pipelines and creating results."""

from bcbench.evaluate.base import EvaluationPipeline, create_pipeline
from bcbench.evaluate.extensibility import compare_extensibility_output

__all__ = ["EvaluationPipeline", "compare_extensibility_output", "create_pipeline"]
