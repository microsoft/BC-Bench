from bcbench.results.base import BaseEvaluationResult


class ExtensibilityResult(BaseEvaluationResult):
    """Result class for extensibility evaluation category."""

    json_output: str | None = None
