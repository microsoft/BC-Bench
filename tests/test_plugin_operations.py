import json
from pathlib import Path

import pytest

from bcbench.exceptions import AgentError
from bcbench.operations import plugin_operations as po
from bcbench.types import AgentType
from tests.conftest import create_dataset_entry


def _make_marketplace(root: Path, manifest_rel: str = ".claude-plugin/marketplace.json", name: str = "probe-mp") -> Path:
    """Create a minimal marketplace directory and return its root."""
    manifest = root / manifest_rel
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({"name": name, "plugins": [{"name": "probe-plugin", "source": "./probe-plugin"}]}), encoding="utf-8")
    plugin_json = root / "probe-plugin" / ".claude-plugin" / "plugin.json"
    plugin_json.parent.mkdir(parents=True, exist_ok=True)
    plugin_json.write_text(json.dumps({"name": "probe-plugin", "version": "0.0.1"}), encoding="utf-8")
    return root


def test_read_marketplace_name_claude_plugin_path(tmp_path):
    _make_marketplace(tmp_path, ".claude-plugin/marketplace.json", name="my-mp")
    assert po._read_marketplace_name(tmp_path) == "my-mp"


def test_read_marketplace_name_github_plugin_path(tmp_path):
    _make_marketplace(tmp_path, ".github/plugin/marketplace.json", name="gh-mp")
    assert po._read_marketplace_name(tmp_path) == "gh-mp"


def test_read_marketplace_name_missing_raises(tmp_path):
    with pytest.raises(AgentError, match=r"marketplace\.json"):
        po._read_marketplace_name(tmp_path)


def test_materialize_marketplace_clones_at_commit(tmp_path, monkeypatch):
    plugins_root = tmp_path / "plugins_root"
    plugins_root.mkdir()

    def fake_clone(repo: str, commit: str, dest: Path) -> None:
        _make_marketplace(dest, name="cloned-mp")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    entry = create_dataset_entry()
    entry_cfg = {"source": "marketplace", "repo": "github/awesome-copilot", "commit": "a" * 40, "plugins": ["probe-plugin"]}

    marketplace_dir, record_suffix = po._materialize(entry_cfg, entry, plugins_root)

    assert (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file()
    assert record_suffix == "a" * 40


def test_materialize_local_copies_from_instructions(tmp_path, monkeypatch):
    plugins_root = tmp_path / "plugins_root"
    plugins_root.mkdir()
    source_root = tmp_path / "instructions"
    _make_marketplace(source_root / "plugins" / "my-mp", name="local-mp")

    monkeypatch.setattr(po, "_get_source_instructions_path", lambda repo: source_root)
    entry = create_dataset_entry()
    entry_cfg = {"source": "local", "path": "plugins/my-mp", "plugins": ["probe-plugin"]}

    marketplace_dir, record_suffix = po._materialize(entry_cfg, entry, plugins_root)

    assert (marketplace_dir / ".claude-plugin" / "marketplace.json").is_file()
    assert record_suffix == "local"


def test_materialize_local_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(po, "_get_source_instructions_path", lambda repo: tmp_path / "nope")
    entry = create_dataset_entry()
    entry_cfg = {"source": "local", "path": "plugins/absent", "plugins": ["x"]}

    with pytest.raises(AgentError, match="Local plugin marketplace not found"):
        po._materialize(entry_cfg, entry, tmp_path / "plugins_root")


def test_materialize_unknown_source_raises(tmp_path):
    entry = create_dataset_entry()
    with pytest.raises(AgentError, match="Unknown plugin source"):
        po._materialize({"source": "bogus", "plugins": []}, entry, tmp_path)


class _Recorder:
    def __init__(self):
        self.calls: list[tuple[list[str], dict | None]] = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs.get("env")))

        class _R:
            returncode = 0

        return _R()


def _marketplace_entry_cfg():
    return {"source": "marketplace", "repo": "github/awesome-copilot", "commit": "a" * 40, "plugins": ["probe-plugin"]}


def test_setup_no_plugins_returns_empty(tmp_path):
    records, env = po.setup_plugins_from_config({}, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")
    assert records == []
    assert env == {}


def test_setup_disabled_entry_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(po.subprocess, "run", _Recorder())
    cfg = {"plugins": [{**_marketplace_entry_cfg(), "enabled": False}]}
    records, env = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")
    assert records == []
    assert env == {}


def test_setup_installs_into_isolated_home_and_records(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    rec = _Recorder()
    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    monkeypatch.setattr(po.subprocess, "run", rec)

    cfg = {"plugins": [_marketplace_entry_cfg()]}
    records, env = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")

    home = str(tmp_path / ".bcbench" / "copilot-home")
    assert records == ["probe-plugin@" + "a" * 40]
    assert env == {"COPILOT_HOME": home}

    add_call = next(c for c in rec.calls if c[0][:4] == ["copilot", "plugin", "marketplace", "add"])
    install_call = next(c for c in rec.calls if c[0][:3] == ["copilot", "plugin", "install"])
    assert add_call[0][4] == str(tmp_path / ".bcbench" / "plugins" / "github-awesome-copilot")
    assert install_call[0] == ["copilot", "plugin", "install", "probe-plugin@awesome-copilot"]
    # commands ran with the isolated home in their env
    assert add_call[1]["COPILOT_HOME"] == home
    assert install_call[1]["COPILOT_HOME"] == home


def test_setup_claude_uses_claude_config_dir(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)
    monkeypatch.setattr(po.subprocess, "run", _Recorder())
    cfg = {"plugins": [_marketplace_entry_cfg()]}

    _records, env = po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.CLAUDE, "claude")

    assert env == {"CLAUDE_CONFIG_DIR": str(tmp_path / ".bcbench" / "claude-home")}


def test_setup_failure_removes_partial_home_and_raises(tmp_path, monkeypatch):
    def fake_clone(repo, commit, dest):
        _make_marketplace(dest, name="awesome-copilot")

    monkeypatch.setattr(po, "clone_at_commit", fake_clone)

    def failing_run(args, **kwargs):
        raise po.subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(po.subprocess, "run", failing_run)
    cfg = {"plugins": [_marketplace_entry_cfg()]}

    with pytest.raises(AgentError, match="Plugin setup failed"):
        po.setup_plugins_from_config(cfg, create_dataset_entry(), tmp_path, AgentType.COPILOT, "copilot")

    assert not (tmp_path / ".bcbench" / "copilot-home").exists()


from unittest.mock import MagicMock, patch

from bcbench.dataset import BaseDatasetEntry


@patch("bcbench.agent.copilot.agent.setup_plugins_from_config")
@patch("bcbench.agent.copilot.agent.parse_tool_usage_from_hooks", return_value=None)
@patch("bcbench.agent.copilot.agent.parse_metrics", return_value=None)
@patch("bcbench.agent.copilot.agent.setup_hooks")
@patch("bcbench.agent.copilot.agent.setup_custom_agent", return_value=None)
@patch("bcbench.agent.copilot.agent.setup_agent_skills", return_value=False)
@patch("bcbench.agent.copilot.agent.setup_instructions_from_config", return_value=False)
@patch("bcbench.agent.copilot.agent.build_al_lsp_plugin", return_value=None)
@patch("bcbench.agent.copilot.agent.build_mcp_config", return_value=(None, None))
@patch("bcbench.agent.copilot.agent.build_prompt", return_value="do the task")
@patch("bcbench.agent.copilot.agent.shutil.which", return_value="copilot")
@patch("bcbench.agent.copilot.agent.subprocess.run")
def test_copilot_runner_records_plugins_and_sets_home(
    mock_run, _which, _prompt, _mcp, _lsp, _instr, _skills, _agent, _hooks, _pm, _tu, mock_setup, tmp_path
):
    from bcbench.agent.copilot.agent import run_copilot_agent
    from bcbench.types import EvaluationCategory

    mock_run.return_value = MagicMock(stderr=b"")
    home = str(tmp_path / ".bcbench" / "copilot-home")
    mock_setup.return_value = (["frontend-web-dev@a1b2c3d4"], {"COPILOT_HOME": home})
    entry = MagicMock(spec=BaseDatasetEntry)
    entry.instance_id = "microsoftInternal__NAV-1"

    _metrics, config = run_copilot_agent(entry=entry, model="m", category=EvaluationCategory.BUG_FIX, repo_path=tmp_path, output_dir=tmp_path)

    assert config.plugins == ["frontend-web-dev@a1b2c3d4"]
    mock_setup.assert_called_once()
    _args, kwargs = mock_run.call_args
    assert kwargs["env"]["COPILOT_HOME"] == home


@patch("bcbench.agent.claude.agent.setup_plugins_from_config")
@patch("bcbench.agent.claude.agent.parse_tool_usage_from_hooks", return_value=None)
@patch("bcbench.agent.claude.agent.parse_metrics", return_value=None)
@patch("bcbench.agent.claude.agent.setup_hooks")
@patch("bcbench.agent.claude.agent.setup_custom_agent", return_value=None)
@patch("bcbench.agent.claude.agent.setup_agent_skills", return_value=False)
@patch("bcbench.agent.claude.agent.setup_instructions_from_config", return_value=False)
@patch("bcbench.agent.claude.agent.build_al_lsp_plugin", return_value=None)
@patch("bcbench.agent.claude.agent.build_mcp_config", return_value=(None, None))
@patch("bcbench.agent.claude.agent.build_prompt", return_value="do the task")
@patch("bcbench.agent.claude.agent.shutil.which", return_value="claude")
@patch("bcbench.agent.claude.agent.subprocess.run")
def test_claude_runner_records_plugins_and_sets_config_dir(
    mock_run, _which, _prompt, _mcp, _lsp, _instr, _skills, _agent, _hooks, _pm, _tu, mock_setup, tmp_path
):
    from bcbench.agent.claude.agent import run_claude_code
    from bcbench.types import EvaluationCategory

    mock_run.return_value = MagicMock(stdout=b'{"result": "ok"}')
    cfg_dir = str(tmp_path / ".bcbench" / "claude-home")
    mock_setup.return_value = (["frontend-web-dev@a1b2c3d4"], {"CLAUDE_CONFIG_DIR": cfg_dir})
    entry = MagicMock(spec=BaseDatasetEntry)
    entry.instance_id = "microsoftInternal__NAV-1"

    _metrics, config = run_claude_code(entry=entry, model="m", category=EvaluationCategory.BUG_FIX, repo_path=tmp_path, output_dir=tmp_path)

    assert config.plugins == ["frontend-web-dev@a1b2c3d4"]
    mock_setup.assert_called_once()
    _args, kwargs = mock_run.call_args
    assert kwargs["env"]["CLAUDE_CONFIG_DIR"] == cfg_dir

