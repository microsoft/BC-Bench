from bcbench.agent.shared import env as env_module
from bcbench.agent.shared.env import agent_subprocess_env


def test_scrubs_bc_connection_vars(monkeypatch):
    monkeypatch.setenv("BC_SERVER_URL", "http://bcbench-sales")
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")
    monkeypatch.setenv("BC_MCP_URL", "http://172.17.0.2:7048/BC")
    monkeypatch.setenv("BC_COMPANY", "CRONUS")
    monkeypatch.setenv("BC_CONTAINER_NAME", "bcbench-sales")

    env = agent_subprocess_env()

    assert not any(k.startswith(("BC_SERVER_", "BC_MCP_")) for k in env)
    assert "BC_COMPANY" not in env
    assert "BC_CONTAINER_NAME" not in env


def test_preserves_other_vars(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")

    env = agent_subprocess_env()

    assert env["PATH"] == "/usr/bin"
    assert "BC_SERVER_PASSWORD" not in env


def test_preserves_bc_connection_vars_when_allowed(monkeypatch):
    monkeypatch.setenv("BC_SERVER_USERNAME", "admin")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")
    monkeypatch.setenv("BC_COMPANY", "CRONUS")
    monkeypatch.setenv("BC_CONTAINER_NAME", "bcbench-sales")

    env = agent_subprocess_env(pass_bc_credentials=True)

    assert env["BC_SERVER_USERNAME"] == "admin"
    assert env["BC_SERVER_PASSWORD"] == "secret"
    assert env["BC_COMPANY"] == "CRONUS"
    assert env["BC_CONTAINER_NAME"] == "bcbench-sales"


def test_overrides_are_applied(monkeypatch):
    monkeypatch.setenv("BC_SERVER_PASSWORD", "secret")

    env = agent_subprocess_env({"FLAG": "on"})

    assert env["FLAG"] == "on"
    assert "BC_SERVER_PASSWORD" not in env


def test_allowlist_preserves_only_explicit_safe_environment(monkeypatch):
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.setenv("TEMP", r"C:\Users\runner\AppData\Local\Temp")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\runner")
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "copilot-token")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "claude-token")
    monkeypatch.setenv("GH_TOKEN", "gh-token")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "azure-secret")
    monkeypatch.setenv("EVALUATOR_SECRET", "evaluator-secret")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "bc-secret")

    env = agent_subprocess_env(allowlist=True)

    assert env["PATH"] == r"C:\Windows\System32"
    assert env["TEMP"] == r"C:\Users\runner\AppData\Local\Temp"
    assert env["USERPROFILE"] == r"C:\Users\runner"
    assert env["COPILOT_GITHUB_TOKEN"] == "copilot-token"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "claude-token"
    assert env["GH_TOKEN"] == "gh-token"
    assert "AZURE_CLIENT_SECRET" not in env
    assert "EVALUATOR_SECRET" not in env
    assert "BC_SERVER_PASSWORD" not in env


def test_allowlist_applies_overrides_after_filtering(monkeypatch):
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "host-secret")
    monkeypatch.setenv("BC_SERVER_PASSWORD", "host-bc-secret")

    env = agent_subprocess_env(
        {
            "AZURE_CLIENT_SECRET": "restricted-secret",
            "BC_SERVER_PASSWORD": "restricted-bc-secret",
        },
        allowlist=True,
    )

    assert env["AZURE_CLIENT_SECRET"] == "restricted-secret"
    assert env["BC_SERVER_PASSWORD"] == "restricted-bc-secret"


def test_allowlist_exactly_matches_task_5_and_preserves_environment_key_casing(monkeypatch):
    allowed_names = {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "COPILOT_GITHUB_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "GH_TOKEN",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "NODE_PATH",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    excluded_names = {
        "OS",
        "PROGRAMW6432",
        "PSMODULEPATH",
        "PUBLIC",
        "USERDOMAIN",
        "USERDOMAIN_ROAMINGPROFILE",
        "USERNAME",
    }
    source_environment = {name.lower(): f"value-for-{name}" for name in allowed_names | excluded_names}
    monkeypatch.setattr(env_module.os, "environ", source_environment)

    env = agent_subprocess_env(allowlist=True)

    assert env == {name.lower(): f"value-for-{name}" for name in allowed_names}
