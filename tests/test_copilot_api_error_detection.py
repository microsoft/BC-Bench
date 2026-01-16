from bcbench.agent.copilot.agent import _is_api_error


def test_is_api_error_with_5xx_error_code():
    assert _is_api_error("500", "Internal Server Error")
    assert _is_api_error("502", "Bad Gateway")
    assert _is_api_error("503", "Service Unavailable")
    assert _is_api_error("504", "Gateway Timeout")


def test_is_api_error_with_rate_limit_code():
    assert _is_api_error("429", "Rate limit exceeded")
    assert _is_api_error("rate_limit_exceeded", "Too many requests")


def test_is_api_error_with_auth_codes():
    assert _is_api_error("401", "Unauthorized")
    assert _is_api_error("403", "Forbidden")
    assert _is_api_error("unauthorized", "Authentication failed")
    assert _is_api_error("authentication_failed", "Invalid credentials")
    assert _is_api_error("invalid_api_key", "API key is invalid")


def test_is_api_error_with_error_message_patterns():
    assert _is_api_error(None, "Rate limit exceeded")
    assert _is_api_error(None, "Quota exceeded for this month")
    assert _is_api_error(None, "Authentication error: invalid API key")
    assert _is_api_error(None, "Unauthorized access")
    assert _is_api_error(None, "Invalid api key provided")
    assert _is_api_error(None, "Server error occurred")
    assert _is_api_error(None, "Internal server error")
    assert _is_api_error(None, "Service unavailable")
    assert _is_api_error(None, "Gateway timeout")
    assert _is_api_error(None, "Bad gateway")
    assert _is_api_error(None, "Error 429: Too many requests")
    assert _is_api_error(None, "Error 500: Internal server error")


def test_is_api_error_with_agent_errors():
    # Agent execution errors should not be classified as API errors
    assert not _is_api_error(None, "Task too complex to complete")
    assert not _is_api_error(None, "Could not find the file")
    assert not _is_api_error(None, "Failed to apply patch")
    assert not _is_api_error(None, "Syntax error in code")
    assert not _is_api_error("agent_error", "Failed to complete task")
    assert not _is_api_error("execution_error", "Tool execution failed")


def test_is_api_error_with_4xx_client_errors():
    # 4xx errors (except auth/rate limit) are not API errors, they're client errors
    assert not _is_api_error("400", "Bad Request")
    assert not _is_api_error("404", "Not Found")
    assert not _is_api_error("422", "Unprocessable Entity")


def test_is_api_error_case_insensitive():
    assert _is_api_error(None, "RATE LIMIT EXCEEDED")
    assert _is_api_error(None, "Rate Limit Exceeded")
    assert _is_api_error("RATE_LIMIT_EXCEEDED", "Error")
    assert _is_api_error("Rate_Limit_Exceeded", "Error")
