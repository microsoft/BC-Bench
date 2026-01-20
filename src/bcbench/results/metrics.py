import math


def pass_hat_k(num_trials: int, success_count: int, k: int) -> float:
    """Measures the probability that all k trials succeed

    Formula: C(success_count, k) / C(num_trials, k)

    Reference: https://arxiv.org/pdf/2406.12045

    Args:
        num_trials: The number of trials (n).
        success_count: The number of successful trials.
        k: The number of trials to consider.

    Returns:
        The pass^k metric (0.0 to 1.0).

    Raises:
        ValueError: If num_trials < k.
    """
    if num_trials < k:
        raise ValueError(f"Number of trials {num_trials} is less than k {k}.")
    return math.comb(success_count, k) / math.comb(num_trials, k)


def pass_at_k(num_samples: int, num_correct: int, k: int) -> float:
    """Measures the likelihood that an agent gets at least one correct solution in k attempts

    Formula: 1 - C(n-c, k) / C(n, k)

    Reference: https://github.com/openai/human-eval-infilling/blob/main/human_eval_infilling/evaluation.py

    Args:
        num_samples: Total number of samples (n).
        num_correct: Number of correct samples (c).
        k: Number of samples to draw.

    Returns:
        The pass@k probability (0.0 to 1.0).

    Raises:
        ValueError: If num_samples < k.
    """
    if num_samples < k:
        raise ValueError(f"Number of samples {num_samples} is less than k {k}.")
    if num_samples - num_correct < k:
        return 1.0
    # Use product formulation to avoid large combinatorial numbers
    # 1 - prod_{i=n-c+1}^{n} (1 - k/i)
    result = 1.0
    for i in range(num_samples - num_correct + 1, num_samples + 1):
        result *= 1.0 - k / i
    return 1.0 - result
