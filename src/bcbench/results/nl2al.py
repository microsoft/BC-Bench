from bcbench.results.base import BaseEvaluationResult


class NL2ALResult(BaseEvaluationResult):
    """Result class for NL2AL evaluation category — evaluated via LLM-as-judge."""

    build: bool = False
    # TODO: populate via LLM-as-judge evaluation
    llm_judge_score: float | None = None
