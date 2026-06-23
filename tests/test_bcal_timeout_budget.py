"""Regression tests tying the bcal retry budget to the CI step timeout.

With retries enabled (``RetryConfig.nl2al_agent_attempts`` > 1) the agent gets several attempts.
Each attempt must be short enough that *all* attempts complete within the GitHub Actions step
``timeout-minutes`` for the bcal evaluation job — otherwise a later attempt is killed mid-run and the
retry silently never helps the thrashing / timed-out cases it exists for.
"""

import re
from pathlib import Path

from bcbench.agent.bcal.agent import _per_attempt_bcal_timeout
from bcbench.config import get_config

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "bcal-evaluation.yml"


def _bcal_step_timeout_seconds() -> int:
    matches = re.findall(r"timeout-minutes:\s*(\d+)", _WORKFLOW.read_text(encoding="utf-8"))
    assert matches, "no timeout-minutes found in bcal-evaluation.yml"
    return min(int(m) for m in matches) * 60


def test_per_attempt_timeout_splits_the_total_budget() -> None:
    config = get_config()
    attempts = max(1, config.retry.nl2al_agent_attempts)
    assert _per_attempt_bcal_timeout() == config.timeout.bcal_execution // attempts


def test_all_retry_attempts_fit_the_ci_step_budget() -> None:
    config = get_config()
    attempts = max(1, config.retry.nl2al_agent_attempts)
    per_attempt = _per_attempt_bcal_timeout()
    step_budget = _bcal_step_timeout_seconds()

    # headroom for per-attempt setup (workspace reset + symbol copy) and graceful shutdown
    overhead_margin = 2 * 60
    assert attempts * per_attempt + overhead_margin <= step_budget, (
        f"{attempts} attempts x {per_attempt}s + {overhead_margin}s overhead "
        f"exceeds the {step_budget}s CI step budget — a retry would be killed mid-run"
    )
