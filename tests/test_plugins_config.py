from unittest.mock import MagicMock, call

import pytest

from bcbench.agent.shared.plugins import install_plugins
from bcbench.exceptions import AgentError


@pytest.fixture
def fake_run(monkeypatch):
    mock = MagicMock(return_value=MagicMock(returncode=0, stderr=""))
    monkeypatch.setattr("bcbench.agent.shared.plugins.subprocess.run", mock)
    return mock


class TestInstallPlugins:
    def test_returns_none_when_no_plugins(self, fake_run):
        assert install_plugins({"plugins": {"install": []}}, "copilot") is None
        assert install_plugins({}, "copilot") is None
        fake_run.assert_not_called()

    def test_installs_and_returns_names(self, fake_run):
        config = {"plugins": {"install": ["foo@awesome-copilot", "bar@copilot-plugins"]}}

        names = install_plugins(config, "copilot")

        assert names == ["foo", "bar"]

    def test_registers_marketplaces_before_install(self, fake_run):
        config = {"plugins": {"marketplaces": ["org/repo"], "install": ["foo@org"]}}

        install_plugins(config, "copilot")

        assert fake_run.call_args_list[0] == call(["copilot", "plugin", "marketplace", "add", "org/repo"], capture_output=True, text=True, check=False)
        assert fake_run.call_args_list[1] == call(["copilot", "plugin", "install", "foo@org"], capture_output=True, text=True, check=False)

    def test_raises_on_failure(self, monkeypatch):
        monkeypatch.setattr("bcbench.agent.shared.plugins.subprocess.run", MagicMock(return_value=MagicMock(returncode=1, stderr="boom")))

        with pytest.raises(AgentError):
            install_plugins({"plugins": {"install": ["foo@org"]}}, "copilot")
