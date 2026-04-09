from bcbench.results.base import BaseEvaluationResult


class NL2ALResult(BaseEvaluationResult):
    """Result class for NL2AL evaluation category.

    Inherits all shared metrics from BaseEvaluationResult.
    """

    # TODO: add llm_judge_score: float | None = None for LLM-as-judge evaluation
