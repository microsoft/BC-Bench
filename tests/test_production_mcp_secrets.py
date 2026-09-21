import json
import logging
import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.claude.agent import run_claude_code
from bcbench.agent.copilot.agent import run_copilot_agent
from bcbench.agent.shared.al_mcp_bridge import AlMcpBridge
from bcbench.agent.shared.contained_process import AgentExecutionPolicy, ContainedProcessRequest, WindowsIdentity, run_contained_process
from bcbench.agent.shared.env import agent_subprocess_env
from bcbench.agent.shared.managed_clients import ManagedAgentClients
from bcbench.agent.shared.mcp import build_mcp_config
from bcbench.types import AgentRuntimeConfig, ContainerConfig, EvaluationCategory
from tests.conftest import create_dataset_entry
from tests.test_al_mcp_bridge import _SERVER

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows process inspection required")
_PROBE = Path(__file__).parent / "fixtures" / "agent_secret_probe.py"


@pytest.mark.parametrize("harness", ["copilot", "claude"])
def test_real_agent_shell_cannot_find_bc_password_in_public_surfaces(tmp_path, monkeypatch, caplog, harness):
    secret = "never-in-agent-surfaces-923741"
    monkeypatch.setenv("BC_SERVER_PASSWORD", secret)
    monkeypatch.setenv("BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD", secret)
    clients = ManagedAgentClients()
    plugin_root = tmp_path / "agent-tools" / "plugins"
    plugin_root.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = AgentExecutionPolicy(contain_process_tree=True, allowlist_environment=True, managed_clients=clients, plugin_root=plugin_root)
    runtime = AgentRuntimeConfig(ContainerConfig("test", "agent", secret, "CRONUS"), al_mcp=True, al_lsp=True)
    config = {
        "mcp": {"servers": [{"name": "altool", "type": "stdio", "command": sys.executable, "args": [str(_SERVER), "launchmcpserver"]}]},
        "plugins": [],
    }
    observed = []

    def shell(command, env):
        prefix = "--additional-mcp-config=" if harness == "copilot" else "--mcp-config="
        mcp = next(arg.removeprefix(prefix) for arg in command if arg.startswith(prefix))
        assert f"--plugin-dir={plugin_root / 'al-lsp-plugin'}" in command
        result = run_contained_process(ContainedProcessRequest((sys.executable, str(_PROBE), mcp), workspace, env, 15))
        assert result.returncode == 0, result.stderr
        observed.append(json.loads(result.stdout))
        return result

    def copilot_shell(**kwargs):
        shell(kwargs["extra_args"], kwargs["env"])
        return None, ""

    def claude_shell(request):
        shell(request.command, request.env)
        return replace(run_result, stdout="{}\n")

    from bcbench.agent.shared.contained_process import ContainedProcessResult

    run_result = ContainedProcessResult(0, "", "")
    which = shutil.which
    module = f"bcbench.agent.{harness}.agent"
    caplog.set_level(logging.DEBUG)
    with (
        patch(f"{module}.yaml.safe_load", return_value=config),
        patch(f"{module}.build_prompt", return_value="run probe"),
        patch("bcbench.agent.shared.lsp._resolve_symbol_paths", return_value=([], [])),
        patch(f"{module}.setup_instructions_from_config", return_value=False),
        patch(f"{module}.setup_agent_skills", return_value=False),
        patch(f"{module}.setup_custom_agent", return_value=None),
        patch("bcbench.agent.copilot.agent.invoke_copilot", side_effect=copilot_shell),
        patch("bcbench.agent.claude.agent.run_contained_process", side_effect=claude_shell),
    ):
        try:
            if harness == "claude":
                with patch("bcbench.agent.claude.agent.shutil.which", side_effect=lambda name: sys.executable if name == "claude" else which(name)):
                    run_claude_code(create_dataset_entry(), "model", EvaluationCategory.BUG_FIX, workspace, workspace, runtime, policy)
            else:
                run_copilot_agent(create_dataset_entry(), "model", EvaluationCategory.BUG_FIX, workspace, workspace, runtime, policy)
        finally:
            clients.stop()

    assert secret not in json.dumps(observed)
    assert secret not in caplog.text
    assert len(observed[0]["processes"]) == 2
    server = observed[0]["config"]["mcpServers"]["altool"]
    assert set(server) == {"type", "url"}
    assert server["url"].startswith("http://127.0.0.1:")
    lsp = json.loads((plugin_root / "al-lsp-plugin" / ".lsp.json").read_text())
    assert ("lspServers" in lsp) == (harness == "copilot")


@pytest.mark.e2e
def test_preprovisioned_restricted_identity_cannot_read_bridge_configuration(tmp_path):
    required = ("USERNAME", "PASSWORD", "WORKSPACE", "PYTHON", "WORKER")
    values = {key: os.environ.get(f"BCBENCH_BRIDGE_TEST_{key}") for key in required}
    if not all(values.values()):
        pytest.skip("requires an explicitly provisioned disposable restricted bridge test identity, workspace, Python and worker")
    username = values["USERNAME"]
    password = values["PASSWORD"]
    workspace_value = values["WORKSPACE"]
    python_value = values["PYTHON"]
    worker_value = values["WORKER"]
    assert username is not None
    assert password is not None
    assert workspace_value is not None
    assert python_value is not None
    assert worker_value is not None
    workspace = Path(workspace_value)
    python = Path(python_value)
    worker = Path(worker_value)
    if not workspace.is_dir() or not python.is_file() or not worker.is_file():
        pytest.fail("preprovisioned bridge test paths must exist")
    secret = "synthetic-bc-credential-restricted-probe"
    clients = ManagedAgentClients()
    runtime = AgentRuntimeConfig(ContainerConfig("test", "agent", secret, "CRONUS"), al_mcp=True)
    config = {"mcp": {"servers": [{"name": "altool", "type": "stdio", "command": sys.executable, "args": [str(_SERVER), "launchmcpserver"]}]}}
    identity = WindowsIdentity(username, password)
    # The probe is passed as code because the production identity cannot read this benchmark tree.
    code = _PROBE.read_text(encoding="utf-8")
    try:
        mcp, _ = build_mcp_config(config, create_dataset_entry(), tmp_path, runtime, managed_clients=clients, require_evaluator_bridge=True)
        assert mcp is not None
        bridge = getattr(clients._stoppers[0], "__self__", None)
        assert isinstance(bridge, AlMcpBridge)
        result = run_contained_process(
            ContainedProcessRequest(
                (str(python), "-c", code, mcp, str(bridge._root / "server.json")),
                workspace,
                agent_subprocess_env(allowlist=True, final_overrides={"TEMP": str(workspace), "TMP": str(workspace)}),
                30,
                identity,
                python_executable=python,
                worker_path=worker,
            )
        )
        assert result.returncode == 0, result.stderr
        assert secret not in result.stdout
        observed = json.loads(result.stdout)
        assert observed["protected_denied"] is True
        assert len(observed["processes"]) == 2
    finally:
        clients.stop()
