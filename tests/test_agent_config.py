import pytest
from pydantic import ValidationError

from bcbench.paths import SHARED_CONFIG_FILE
from bcbench.types import AgentConfig


def test_shipped_config_is_valid():
    AgentConfig.from_file(SHARED_CONFIG_FILE)


def test_absent_sections_are_disabled():
    config = AgentConfig.model_validate({})

    assert not config.instructions.enabled
    assert not config.skills.enabled
    assert not config.agents.enabled
    assert config.agents.name is None
    assert config.mcp.servers == ()


@pytest.mark.parametrize(
    "data",
    [
        pytest.param({"instructions": {"enabeld": True}}, id="misspelled-toggle-key"),
        pytest.param({"instructions": True}, id="toggle-section-not-a-mapping"),
        pytest.param({"skills": {"enabled": "yes"}}, id="toggle-string-not-bool"),
        pytest.param({"agents": {"enabled": 1}}, id="toggle-int-not-bool"),
        pytest.param({"prompt": {"include_project_paths": "true"}}, id="prompt-string-not-bool"),
        pytest.param({"instrucions": {"enabled": True}}, id="misspelled-section"),
        pytest.param({"mcp": {"server": []}}, id="misspelled-mcp-key"),
        pytest.param({"prompt": {"templates": {"bug-fix": "x"}}}, id="prompt-templates-key"),
    ],
)
def test_malformed_config_is_rejected(data):
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(data)


@pytest.mark.parametrize(
    ("server", "expected_type"),
    [
        ({"name": "altool", "type": "http", "url": "http://localhost"}, "stdio"),
        ({"name": "bcmcp", "type": "stdio", "command": "bcmcp"}, "http"),
    ],
)
def test_reserved_mcp_server_requires_its_type(server, expected_type):
    with pytest.raises(ValidationError, match=f"must be of type '{expected_type}'"):
        AgentConfig.model_validate({"mcp": {"servers": [server]}})
