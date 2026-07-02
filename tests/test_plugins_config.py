from unittest.mock import MagicMock

import pytest

from bcbench.agent.shared.plugins import install_plugins
from bcbench.exceptions import AgentError

PLUGIN_SPEC = {
    "repo": "github/awesome-copilot",
    "sha": "28c3a14af4e6232091071ddb40272f72d9d96b2f",
    "name": "awesome-copilot@awesome-copilot",
}


@pytest.fixture
def fake_run(monkeypatch):
    mock = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
    monkeypatch.setattr("bcbench.agent.shared.plugins.subprocess.run", mock)
    return mock


@pytest.fixture(autouse=True)
def fake_mkdtemp(monkeypatch):
    monkeypatch.setattr("bcbench.agent.shared.plugins.tempfile.mkdtemp", lambda **_: "/tmp/market")


def _commands(fake_run) -> list[list[str]]:
    return [c.args[0] for c in fake_run.call_args_list]


class TestInstallPlugins:
    def test_returns_none_when_no_plugins(self, fake_run):
        assert install_plugins({"plugins": {"install": []}}, "copilot") is None
        assert install_plugins({}, "claude") is None
        fake_run.assert_not_called()

    def test_returns_plugin_names(self, fake_run):
        names = install_plugins({"plugins": {"install": [PLUGIN_SPEC]}}, "copilot")

        assert names == ["awesome-copilot"]

    def test_clones_marketplace_pinned_to_sha(self, fake_run):
        install_plugins({"plugins": {"install": [PLUGIN_SPEC]}}, "copilot")

        commands = _commands(fake_run)
        assert commands[0] == ["git", "clone", "--quiet", "https://github.com/github/awesome-copilot.git", "/tmp/market"]
        assert commands[1] == ["git", "-C", "/tmp/market", "checkout", "--quiet", "28c3a14af4e6232091071ddb40272f72d9d96b2f"]

    def test_always_adds_marketplace_then_installs(self, fake_run):
        install_plugins({"plugins": {"install": [PLUGIN_SPEC]}}, "claude")

        commands = _commands(fake_run)
        assert commands[2] == ["claude", "plugin", "marketplace", "add", "/tmp/market"]
        assert commands[3] == ["claude", "plugin", "install", "awesome-copilot@awesome-copilot"]

    def test_uses_provided_cli_command(self, fake_run):
        install_plugins({"plugins": {"install": [PLUGIN_SPEC]}}, "copilot")

        cli_commands = [c for c in _commands(fake_run) if c[0] != "git"]
        assert all(c[0] == "copilot" for c in cli_commands)

    def test_full_git_url_repo(self, fake_run):
        spec = {**PLUGIN_SPEC, "repo": "https://gitlab.com/o/r.git"}

        install_plugins({"plugins": {"install": [spec]}}, "copilot")

        assert _commands(fake_run)[0] == ["git", "clone", "--quiet", "https://gitlab.com/o/r.git", "/tmp/market"]

    def test_raises_on_failure(self, monkeypatch):
        monkeypatch.setattr("bcbench.agent.shared.plugins.subprocess.run", MagicMock(return_value=MagicMock(returncode=1, stderr="boom")))

        with pytest.raises(AgentError):
            install_plugins({"plugins": {"install": [PLUGIN_SPEC]}}, "copilot")
