from typing import Self

from bcbench.results.base import BaseEvaluationResult
from bcbench.types import EvaluationContext


class NL2ALResult(BaseEvaluationResult):
    """Result class for NL2AL evaluation category — evaluated via LLM-as-judge."""

    build: bool = False
    # TODO: populate via LLM-as-judge evaluation
    llm_judge_score: float | None = None

    @classmethod
    def create_build_failure(cls, context: "EvaluationContext", output: str, error_message: str) -> Self:
        return cls(**cls._base_fields(context), output=output, error_message=error_message, build=False)

    @classmethod
    def create_build_success(cls, context: "EvaluationContext", output: str, llm_judge_score: float | None = None) -> Self:
        return cls(**cls._base_fields(context), output=output, build=True, llm_judge_score=llm_judge_score)
