import logging

from bcbench.results.bugfix import BugFixResult
from bcbench.types import AgentMetrics, AgentName
from tests.conftest import create_evaluation_context


def _missing_metric_warnings(caplog) -> list[str]:
    return [record.message for record in caplog.records if record.levelno == logging.WARNING and "missing metrics" in record.message]


class TestExpectedMetricsWarning:
    def test_no_warning_when_agent_does_not_collect_metric(self, tmp_path, caplog):
        context = create_evaluation_context(tmp_path, agent_name=AgentName.BCAL)
        context.metrics = AgentMetrics(execution_time=12.0)

        with caplog.at_level(logging.WARNING):
            BugFixResult.create_success(context, "patch")

        assert _missing_metric_warnings(caplog) == []

    def test_warns_when_expected_metric_is_missing(self, tmp_path, caplog):
        context = create_evaluation_context(tmp_path, agent_name=AgentName.COPILOT)
        context.metrics = AgentMetrics(execution_time=12.0, llm_duration=5.0, prompt_tokens=100, completion_tokens=10, tool_usage={"bash": 1})

        with caplog.at_level(logging.WARNING):
            BugFixResult.create_success(context, "patch")

        assert _missing_metric_warnings(caplog) == [f"Result for {context.entry.instance_id} missing metrics: turn_count"]

    def test_warns_when_no_metrics_at_all(self, tmp_path, caplog):
        context = create_evaluation_context(tmp_path, agent_name=AgentName.BCAL)

        with caplog.at_level(logging.WARNING):
            BugFixResult.create_success(context, "patch")

        assert any("no agent metrics" in record.message for record in caplog.records)

    def test_full_metric_agents_expect_every_field(self):
        assert AgentName.COPILOT.expected_metrics == AgentMetrics.field_names()
        assert AgentName.CLAUDE.expected_metrics == AgentMetrics.field_names()

    def test_agent_name_serializes_as_plain_string(self, tmp_path):
        context = create_evaluation_context(tmp_path, agent_name=AgentName.BCAL)
        result = BugFixResult.create_success(context, "patch")

        assert result.model_dump(mode="json")["agent_name"] == "BCal"
