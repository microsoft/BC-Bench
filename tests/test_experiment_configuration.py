"""Test ExperimentConfiguration dataclass."""

from bcbench.types import ExperimentConfiguration


class TestExperimentConfiguration:
    def test_default_values(self):
        config = ExperimentConfiguration()

        assert config.agent_metrics is None
        assert config.mcp_servers is None
        assert config.custom_instructions is False
        assert config.custom_agent is None

    def test_with_metrics_only(self):
        metrics = {"agent_execution_time": 120.5, "prompt_tokens": 1000, "completion_tokens": 500}
        config = ExperimentConfiguration(agent_metrics=metrics)

        assert config.agent_metrics == metrics
        assert config.mcp_servers is None
        assert config.custom_instructions is False
        assert config.custom_agent is None

    def test_with_mcp_servers(self):
        mcp_servers = ["mcp-server-1", "mcp-server-2"]
        config = ExperimentConfiguration(mcp_servers=mcp_servers)

        assert config.agent_metrics is None
        assert config.mcp_servers == mcp_servers
        assert config.custom_instructions is False
        assert config.custom_agent is None

    def test_with_custom_instructions(self):
        config = ExperimentConfiguration(custom_instructions=True)

        assert config.agent_metrics is None
        assert config.mcp_servers is None
        assert config.custom_instructions is True
        assert config.custom_agent is None

    def test_with_custom_agent(self):
        config = ExperimentConfiguration(custom_agent="my-custom-agent")

        assert config.agent_metrics is None
        assert config.mcp_servers is None
        assert config.custom_instructions is False
        assert config.custom_agent == "my-custom-agent"

    def test_with_all_fields(self):
        metrics = {"agent_execution_time": 200.0, "prompt_tokens": 5000}
        mcp_servers = ["server-1"]
        custom_agent = "test-agent"

        config = ExperimentConfiguration(
            agent_metrics=metrics,
            mcp_servers=mcp_servers,
            custom_instructions=True,
            custom_agent=custom_agent,
        )

        assert config.agent_metrics == metrics
        assert config.mcp_servers == mcp_servers
        assert config.custom_instructions is True
        assert config.custom_agent == custom_agent

    def test_empty_metrics_dict(self):
        config = ExperimentConfiguration(agent_metrics={})

        assert config.agent_metrics == {}
        assert config.mcp_servers is None
        assert config.custom_instructions is False
        assert config.custom_agent is None

    def test_empty_mcp_servers_list(self):
        config = ExperimentConfiguration(mcp_servers=[])

        assert config.agent_metrics is None
        assert config.mcp_servers == []
        assert config.custom_instructions is False
        assert config.custom_agent is None
