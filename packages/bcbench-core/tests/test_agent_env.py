from bcbench_core.agent.env import agent_subprocess_env

_BC_ENV = {
    "BC_SERVER_URL": "http://bcbench-sales",
    "BC_SERVER_USERNAME": "admin",
    "BC_SERVER_PASSWORD": "secret",
    "BC_MCP_URL": "http://172.17.0.2:7048/BC",
    "BC_COMPANY": "CRONUS",
    "BC_CONTAINER_NAME": "bcbench-sales",
}


def test_scrubs_bc_connection_vars():
    env = agent_subprocess_env(_BC_ENV)

    assert not any(k.startswith(("BC_SERVER_", "BC_MCP_")) for k in env)
    assert "BC_COMPANY" not in env
    assert "BC_CONTAINER_NAME" not in env


def test_preserves_other_vars():
    env = agent_subprocess_env({"PATH": "/usr/bin", "BC_SERVER_PASSWORD": "secret"})

    assert env["PATH"] == "/usr/bin"
    assert "BC_SERVER_PASSWORD" not in env


def test_preserves_bc_connection_vars_when_allowed():
    env = agent_subprocess_env(_BC_ENV, pass_bc_credentials=True)

    assert env["BC_SERVER_USERNAME"] == "admin"
    assert env["BC_SERVER_PASSWORD"] == "secret"
    assert env["BC_COMPANY"] == "CRONUS"
    assert env["BC_CONTAINER_NAME"] == "bcbench-sales"


def test_overrides_are_applied_and_parent_env_is_not_mutated():
    parent = {"BC_SERVER_PASSWORD": "secret"}

    env = agent_subprocess_env(parent, {"FLAG": "on"})

    assert parent == {"BC_SERVER_PASSWORD": "secret"}

    assert env["FLAG"] == "on"
    assert "BC_SERVER_PASSWORD" not in env
