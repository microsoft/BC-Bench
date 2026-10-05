from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

_HTTP_STATUS_PATTERN = re.compile(
    r"\b(?:http(?: status)?|status[_ ]?code|response|error code|server returned)[^0-9\n]{0,16}(429|5\d{2})\b",
    re.IGNORECASE,
)
_TRANSIENT_MESSAGE_MARKERS = (
    "dependencyfailure",
    "dependency failure",
    "too many requests",
    "rate limit",
    "temporarily unavailable",
    "internal server error",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "circuit breaker",
    "connection reset",
    "connection aborted",
    "connection timed out",
    "read timed out",
)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    initial_delay_seconds: float = 10
    max_delay_seconds: float = 60

    def delay_after(self, failed_attempt: int) -> float:
        return min(self.initial_delay_seconds * (2 ** (failed_attempt - 1)), self.max_delay_seconds)


_DEFAULT_RETRY_POLICY = RetryPolicy()


def is_transient_dependency_failure(error: BaseException) -> bool:
    for current in _exception_chain(error):
        status_codes = {
            _integer_status(getattr(current, "status_code", None)),
            _integer_status(getattr(current, "status", None)),
            _integer_status(getattr(getattr(current, "response", None), "status_code", None)),
        }
        if any(status == 429 or (status is not None and 500 <= status <= 599) for status in status_codes):
            return True

        message = str(current).lower()
        if _HTTP_STATUS_PATTERN.search(message) or any(marker in message for marker in _TRANSIENT_MESSAGE_MARKERS):
            return True

        if isinstance(current, (ConnectionError, TimeoutError)):
            return True

    return False


def retry_transient[T](
    operation: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
) -> T:
    policy = policy or _DEFAULT_RETRY_POLICY
    if policy.max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(1, policy.max_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if attempt == policy.max_attempts or not is_transient_dependency_failure(error):
                raise

            delay = policy.delay_after(attempt)
            if on_retry:
                on_retry(error, attempt, delay)
            sleep(delay)

    raise AssertionError("Retry loop exhausted without returning or raising")


def _exception_chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _integer_status(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
