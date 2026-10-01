from bcbench_core.statistics import bootstrap_ci, f1_score, f_beta_score, pass_at_k, pass_hat_k
from bcbench_core.statistics import precision_recall as core_precision_recall

__all__ = ["bootstrap_ci", "f1_score", "f_beta_score", "pass_at_k", "pass_hat_k", "precision_recall"]


def precision_recall(matched_count: int, generated_count: int, expected_count: int) -> tuple[float, float]:
    """Treat empty generated or expected sets as perfect precision or recall."""
    return core_precision_recall(matched_count, generated_count, expected_count, empty_precision=1.0, empty_recall=1.0)
