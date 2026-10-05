from __future__ import annotations

import pytest

from bcbench.retry import RetryPolicy, is_transient_dependency_failure, retry_transient


class HttpError(Exception):
    def __init__(self, status_code: int, message: str = ""):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize(
    "error",
    [
        HttpError(429),
        HttpError(500),
        HttpError(529),
        RuntimeError("DependencyFailure: Internal server error"),
        RuntimeError("all deployments temporarily unavailable / circuit breaker open"),
        ConnectionError("connection reset"),
    ],
)
def test_transient_dependency_failures_are_recognized(error):
    assert is_transient_dependency_failure(error)


@pytest.mark.parametrize(
    "error",
    [
        HttpError(400, "invalid request"),
        ValueError("AL compilation failed"),
        RuntimeError("content assertion did not match"),
        RuntimeError("expected 500 tokens in generated content"),
    ],
)
def test_deterministic_failures_are_not_retried(error):
    assert not is_transient_dependency_failure(error)


def test_retry_transient_uses_bounded_exponential_delays():
    attempts = 0
    delays = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 4:
            raise HttpError(529)
        return "ok"

    result = retry_transient(
        operation,
        policy=RetryPolicy(max_attempts=4, initial_delay_seconds=2, max_delay_seconds=5),
        sleep=delays.append,
    )

    assert result == "ok"
    assert attempts == 4
    assert delays == [2, 4, 5]


def test_retry_transient_propagates_deterministic_failure_without_sleeping():
    delays = []

    with pytest.raises(ValueError, match="compile"):
        retry_transient(lambda: (_ for _ in ()).throw(ValueError("compile failed")), sleep=delays.append)

    assert delays == []
