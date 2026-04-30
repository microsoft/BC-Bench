"""Tests for instruction setup operations."""

import pytest

from bcbench.operations.instruction_operations import (
    _get_source_instructions_path,
    copy_problem_statement_folder,
    setup_custom_agent,
    setup_instructions_from_config,
)
from bcbench.types import AgentType
from tests.conftest import create_dataset_entry, create_problem_statement_dir


def _make_agent_config(instructions_enabled: bool = True, agents_enabled: bool = False, agent_name: str | None = None) -> dict:
    return {
        "instructions": {"enabled": instructions_enabled},
        "agents": {"enabled": agents_enabled, "name": agent_name},
    }


class TestSetupInstructionsFromConfig:
    def test_disabled_returns_false(self, tmp_path):
        entry = create_dataset_entry()
        config = _make_agent_config(instructions_enabled=False)

        result = setup_instructions_from_config(config, entry, tmp_path, AgentType.COPILOT)

        assert result is False

    def test_enabled_returns_true(self, tmp_path):
        from unittest.mock import patch

        entry = create_dataset_entry(repo="microsoftInternal/NAV")
        instructions_dir = tmp_path / "instructions" / "microsoftInternal-NAV"
        instructions_dir.mkdir(parents=True)
        (instructions_dir / "AGENTS.md").write_text("instructions content")
        config = _make_agent_config(instructions_enabled=True)

        with patch("bcbench.operations.instruction_operations._get_source_instructions_path", return_value=instructions_dir):
            result = setup_instructions_from_config(config, entry, tmp_path / "repo", AgentType.COPILOT)

        assert result is True

    def test_enabled_copies_instructions(self, tmp_path):
        from unittest.mock import patch

        entry = create_dataset_entry(repo="microsoftInternal/NAV")
        instructions_dir = tmp_path / "instructions" / "microsoftInternal-NAV"
        instructions_dir.mkdir(parents=True)
        (instructions_dir / "AGENTS.md").write_text("my instructions")

        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("bcbench.operations.instruction_operations._get_source_instructions_path", return_value=instructions_dir):
            setup_instructions_from_config(_make_agent_config(True), entry, repo_path, AgentType.COPILOT)

        # For Copilot, target dir is repo/.github
        assert (repo_path / ".github").exists()

    def test_enabled_renames_canonical_to_agent_specific(self, tmp_path):
        from unittest.mock import patch

        entry = create_dataset_entry(repo="microsoftInternal/NAV")
        instructions_dir = tmp_path / "instructions" / "microsoftInternal-NAV"
        instructions_dir.mkdir(parents=True)
        (instructions_dir / "AGENTS.md").write_text("instructions")  # Canonical name

        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        with patch("bcbench.operations.instruction_operations._get_source_instructions_path", return_value=instructions_dir):
            setup_instructions_from_config(_make_agent_config(True), entry, repo_path, AgentType.COPILOT)

        # AGENTS.md should be renamed to copilot-instructions.md
        assert (repo_path / ".github" / "copilot-instructions.md").exists()
        assert not (repo_path / ".github" / "AGENTS.md").exists()


class TestSetupCustomAgent:
    def test_disabled_returns_none(self, tmp_path):
        entry = create_dataset_entry()
        config = _make_agent_config(agents_enabled=False)

        result = setup_custom_agent(config, entry, tmp_path, AgentType.COPILOT)

        assert result is None

    def test_enabled_returns_agent_name(self, tmp_path):
        from unittest.mock import patch

        entry = create_dataset_entry(repo="microsoftInternal/NAV")
        instructions_dir = tmp_path / "instructions" / "microsoftInternal-NAV"
        agents_dir = instructions_dir / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "agent.yml").write_text("agent config")

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        config = _make_agent_config(agents_enabled=True, agent_name="my-agent")

        with patch("bcbench.operations.instruction_operations._get_source_instructions_path", return_value=instructions_dir):
            result = setup_custom_agent(config, entry, repo_path, AgentType.COPILOT)

        assert result == "my-agent"

    def test_enabled_none_agent_name_returns_none(self, tmp_path):
        from unittest.mock import patch

        entry = create_dataset_entry(repo="microsoftInternal/NAV")
        instructions_dir = tmp_path / "instructions" / "microsoftInternal-NAV"
        agents_dir = instructions_dir / "agents"
        agents_dir.mkdir(parents=True)

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        config = _make_agent_config(agents_enabled=True, agent_name=None)

        with patch("bcbench.operations.instruction_operations._get_source_instructions_path", return_value=instructions_dir):
            result = setup_custom_agent(config, entry, repo_path, AgentType.COPILOT)

        assert result is None


class TestGetSourceInstructionsPath:
    def test_raises_when_not_found(self, tmp_path):
        from unittest.mock import MagicMock, patch

        mock_config = MagicMock()
        mock_config.paths.agent_share_dir = tmp_path
        mock_config.file_patterns.instructions_dirname = "instructions"

        with patch("bcbench.operations.instruction_operations._config", mock_config), pytest.raises(FileNotFoundError, match="Instruction folder not found"):
            _get_source_instructions_path("nonexistent/repo")

    def test_returns_path_when_found(self, tmp_path):
        from unittest.mock import MagicMock, patch

        instructions_dir = tmp_path / "instructions" / "my-org-repo"
        instructions_dir.mkdir(parents=True)

        mock_config = MagicMock()
        mock_config.paths.agent_share_dir = tmp_path
        mock_config.file_patterns.instructions_dirname = "instructions"

        with patch("bcbench.operations.instruction_operations._config", mock_config):
            result = _get_source_instructions_path("my-org/repo")

        assert result == instructions_dir

    def test_sanitizes_slash_to_dash(self, tmp_path):
        from unittest.mock import MagicMock, patch

        instructions_dir = tmp_path / "instructions" / "org-name-repo-name"
        instructions_dir.mkdir(parents=True)

        mock_config = MagicMock()
        mock_config.paths.agent_share_dir = tmp_path
        mock_config.file_patterns.instructions_dirname = "instructions"

        with patch("bcbench.operations.instruction_operations._config", mock_config):
            result = _get_source_instructions_path("org-name/repo-name")

        assert result == instructions_dir


class TestCopyProblemStatementFolder:
    def test_copies_folder_to_dest(self, tmp_path):
        from unittest.mock import MagicMock, patch

        entry = create_dataset_entry()
        problem_dir = create_problem_statement_dir(tmp_path)
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        mock_config = MagicMock()
        mock_config.file_patterns.problem_statement_dest_dir = "problem"

        with (
            patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)),
            patch("bcbench.operations.instruction_operations._config", mock_config),
        ):
            copy_problem_statement_folder(entry, repo_path)

        assert (repo_path / "problem").exists()
        assert (repo_path / "problem" / "README.md").exists()

    def test_overwrites_existing_dest(self, tmp_path):
        from unittest.mock import MagicMock, patch

        entry = create_dataset_entry()
        problem_dir = create_problem_statement_dir(tmp_path, "new content")
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        # Create existing dest dir with stale content
        dest = repo_path / "problem"
        dest.mkdir()
        (dest / "old_file.txt").write_text("stale")

        mock_config = MagicMock()
        mock_config.file_patterns.problem_statement_dest_dir = "problem"

        with (
            patch.object(type(entry), "problem_statement_dir", property(lambda self: problem_dir)),
            patch("bcbench.operations.instruction_operations._config", mock_config),
        ):
            copy_problem_statement_folder(entry, repo_path)

        # Old file should be gone, new README present
        assert not (repo_path / "problem" / "old_file.txt").exists()
        assert (repo_path / "problem" / "README.md").exists()
        assert (repo_path / "problem" / "README.md").read_text() == "new content"
