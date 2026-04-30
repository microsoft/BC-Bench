"""Tests for types.py - AgentType, EvaluationCategory, EvaluationContext."""

import pytest

from bcbench.types import AgentType, ExperimentConfiguration
from tests.conftest import create_evaluation_context


class TestAgentType:
    def test_claude_instruction_filename(self):
        assert AgentType.CLAUDE.instruction_filename == "CLAUDE.md"

    def test_copilot_instruction_filename(self):
        assert AgentType.COPILOT.instruction_filename == "copilot-instructions.md"

    def test_claude_target_dir(self, tmp_path):
        target = AgentType.CLAUDE.get_target_dir(tmp_path)
        assert target == tmp_path / ".claude"

    def test_copilot_target_dir(self, tmp_path):
        target = AgentType.COPILOT.get_target_dir(tmp_path)
        assert target == tmp_path / ".github"


class TestEvaluationContext:
    def test_get_container_raises_when_none(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)
        ctx.container = None

        with pytest.raises(ValueError, match="Container configuration is required"):
            ctx.get_container()

    def test_get_container_returns_container_when_set(self, tmp_path):
        ctx = create_evaluation_context(tmp_path)

        container = ctx.get_container()
        assert container is not None
        assert container.name == "test-container"


class TestExperimentConfiguration:
    def test_is_empty_default(self):
        config = ExperimentConfiguration()
        assert config.is_empty() is True

    def test_is_empty_with_mcp_servers(self):
        config = ExperimentConfiguration(mcp_servers=["altool"])
        assert config.is_empty() is False

    def test_is_empty_with_custom_instructions(self):
        config = ExperimentConfiguration(custom_instructions=True)
        assert config.is_empty() is False

    def test_is_empty_with_skills(self):
        config = ExperimentConfiguration(skills_enabled=True)
        assert config.is_empty() is False

    def test_is_empty_with_custom_agent(self):
        config = ExperimentConfiguration(custom_agent="my-agent")
        assert config.is_empty() is False
