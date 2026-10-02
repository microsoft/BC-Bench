import numpy as np
from scipy.stats import bootstrap as scipy_bootstrap


def bootstrap_ci(values: list[float] | np.ndarray, n_bootstrap: int = 10000, ci_level: float = 0.95) -> dict[str, float | None]:
    data = np.asarray(values, dtype=float)
    mean = float(data.mean()) if len(data) >= 1 else 0.0
    if len(data) < 2:
        return {"mean": mean, "ci_low": None, "ci_high": None}
    # BCa is undefined for zero-variance data (jackknife acceleration divides by zero)
    if np.all(data == data[0]):
        return {"mean": mean, "ci_low": None, "ci_high": None}
    result = scipy_bootstrap(
        (data,),
        statistic=np.mean,
        n_resamples=n_bootstrap,
        confidence_level=ci_level,
        method="BCa",
        rng=np.random.default_rng(42),
    )
    return {
        "mean": mean,
        "ci_low": float(result.confidence_interval.low),
        "ci_high": float(result.confidence_interval.high),
    }
