"""Test ExperimentConfiguration dataclass."""

from bcbench.types import ExperimentConfiguration


class TestExperimentConfiguration:
    def test_default_values(self):
        config = ExperimentConfiguration()

        assert config.mcp_servers is None
        assert config.custom_instructions is False
        assert config.custom_agent is None

    def test_with_mcp_servers(self):
        mcp_servers = ["mcp-server-1", "mcp-server-2"]
        config = ExperimentConfiguration(mcp_servers=mcp_servers)

        assert config.mcp_servers == mcp_servers
        assert config.custom_instructions is False
        assert config.custom_agent is None

    def test_with_custom_instructions(self):
        config = ExperimentConfiguration(custom_instructions=True)

        assert config.mcp_servers is None
        assert config.custom_instructions is True
        assert config.custom_agent is None

    def test_with_custom_agent(self):
        config = ExperimentConfiguration(custom_agent="my-custom-agent")

        assert config.mcp_servers is None
        assert config.custom_instructions is False
        assert config.custom_agent == "my-custom-agent"

    def test_with_all_fields(self):
        mcp_servers = ["server-1"]
        custom_agent = "test-agent"

        config = ExperimentConfiguration(
            mcp_servers=mcp_servers,
            custom_instructions=True,
            custom_agent=custom_agent,
        )

        assert config.mcp_servers == mcp_servers
        assert config.custom_instructions is True
        assert config.custom_agent == custom_agent

    def test_empty_mcp_servers_list(self):
        config = ExperimentConfiguration(mcp_servers=[])

        assert config.mcp_servers == []
        assert config.custom_instructions is False
        assert config.custom_agent is None
