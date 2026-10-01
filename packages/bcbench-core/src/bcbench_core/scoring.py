def precision_recall(matched: int, generated: int, expected: int) -> tuple[float, float]:
    precision = matched / generated if generated else 1.0
    recall = matched / expected if expected else 1.0
    return precision, recall


def f_beta_score(precision: float, recall: float, beta: float) -> float:
    if precision == 0.0 and recall == 0.0:
        return 0.0
    beta_squared = beta**2
    return (1 + beta_squared) * precision * recall / (beta_squared * precision + recall)


def f1_score(precision: float, recall: float) -> float:
    return f_beta_score(precision, recall, beta=1.0)
