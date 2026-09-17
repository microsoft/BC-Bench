from bcbench.exceptions import AgentTimeoutError


def test_agent_timeout_error_streams_default_to_none():
    error = AgentTimeoutError("timed out")

    assert error.stdout is None
    assert error.stderr is None
