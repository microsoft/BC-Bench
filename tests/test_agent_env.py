from bcbench.agent.shared.env import agent_subprocess_env


def test_scrubs_bc_connection_vars(monkeypatch):
    monkeypatch.setenv("BC_SERVER_URL", "http://bcbench-sales")
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")
    monkeypatch.setenv("BC_MCP_URL", "http://172.17.0.2:7048/BC")
    monkeypatch.setenv("BC_MCP_COMPANY", "CRONUS")
    monkeypatch.setenv("BC_CONTAINER_NAME", "bcbench-sales")

    env = agent_subprocess_env()

    assert not any(k.startswith(("BC_SERVER_", "BC_MCP_")) for k in env)
    assert "BC_CONTAINER_NAME" not in env


def test_preserves_other_vars(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")

    env = agent_subprocess_env()

    assert env["PATH"] == "/usr/bin"
    assert "BC_SERVER_PASSWORD" not in env


def test_overrides_are_applied(monkeypatch):
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")

    env = agent_subprocess_env({"FLAG": "on"})

    assert env["FLAG"] == "on"
    assert "BC_SERVER_PASSWORD" not in env
