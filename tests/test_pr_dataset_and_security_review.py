"""Tests for PR dataset and security review prompt functionality."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from bcbench.agent.copilot.prompt import build_pr_review_prompt
from bcbench.agent.pr_security_review_helper import build_pr_security_review_prompt, load_pr_dataset
from bcbench.dataset import PRDatasetEntry, TargetComment, load_pr_dataset_entries


class TestPRDatasetEntry:
    def test_from_json_basic(self):
        """Test creating PRDatasetEntry from JSON."""
        payload = {
            "name": "Update EInvoiceSaaSCommunication.Codeunit.al",
            "description": "Update to use Text instead of SecretText",
            "diff": "--- a/file\n+++ b/file\n@@ -1 +1 @@",
            "target_comments": [
                {"comment": "Issue 1", "line": 114},
                {"comment": "Issue 2", "line": 133},
            ],
        }

        entry = PRDatasetEntry.from_json(payload)

        assert entry.name == "Update EInvoiceSaaSCommunication.Codeunit.al"
        assert entry.description == "Update to use Text instead of SecretText"
        assert entry.diff == "--- a/file\n+++ b/file\n@@ -1 +1 @@"
        assert len(entry.target_comments) == 2
        assert entry.target_comments[0]["comment"] == "Issue 1"
        assert entry.target_comments[0]["line"] == 114

    def test_from_json_empty_target_comments(self):
        """Test PRDatasetEntry with empty target comments."""
        payload = {
            "name": "Test PR",
            "description": "Test",
            "diff": "test diff",
            "target_comments": [],
        }

        entry = PRDatasetEntry.from_json(payload)

        assert entry.target_comments == []

    def test_from_json_missing_optional_fields(self):
        """Test PRDatasetEntry handles missing optional fields."""
        payload = {"name": "Test PR"}

        entry = PRDatasetEntry.from_json(payload)

        assert entry.name == "Test PR"
        assert entry.description == ""
        assert entry.diff == ""
        assert entry.target_comments == []

    def test_to_dict(self):
        """Test converting PRDatasetEntry back to dict."""
        entry = PRDatasetEntry(
            name="Test PR",
            description="Test description",
            diff="test diff",
            target_comments=[
                TargetComment(comment="Comment 1", line=10),
                TargetComment(comment="Comment 2", line=20),
            ],
        )

        result = entry.to_dict()

        assert result["name"] == "Test PR"
        assert result["description"] == "Test description"
        assert result["diff"] == "test diff"
        assert len(result["target_comments"]) == 2


class TestLoadPRDatasetEntries:
    def test_load_entries_from_jsonl(self, tmp_path):
        """Test loading PR dataset entries from JSONL file."""
        dataset_file = tmp_path / "prdataset.jsonl"
        entries_data = [
            {
                "name": "PR 1",
                "description": "Description 1",
                "diff": "diff 1",
                "target_comments": [{"comment": "Comment 1", "line": 1}],
            },
            {
                "name": "PR 2",
                "description": "Description 2",
                "diff": "diff 2",
                "target_comments": [{"comment": "Comment 2", "line": 2}],
            },
        ]

        with dataset_file.open("w") as f:
            for data in entries_data:
                f.write(json.dumps(data) + "\n")

        entries = load_pr_dataset_entries(dataset_file)

        assert len(entries) == 2
        assert entries[0].name == "PR 1"
        assert entries[1].name == "PR 2"

    def test_load_entries_nonexistent_file(self, tmp_path):
        """Test loading from non-existent file returns empty list."""
        nonexistent = tmp_path / "nonexistent.jsonl"

        entries = load_pr_dataset_entries(nonexistent)

        assert entries == []

    def test_load_entries_skip_empty_lines(self, tmp_path):
        """Test that empty lines are skipped."""
        dataset_file = tmp_path / "prdataset.jsonl"
        with dataset_file.open("w") as f:
            f.write(json.dumps({"name": "PR 1", "description": "", "diff": "", "target_comments": []}) + "\n")
            f.write("\n")  # Empty line
            f.write(json.dumps({"name": "PR 2", "description": "", "diff": "", "target_comments": []}) + "\n")

        entries = load_pr_dataset_entries(dataset_file)

        assert len(entries) == 2

    def test_load_entries_invalid_json(self, tmp_path):
        """Test that invalid JSON raises error."""
        dataset_file = tmp_path / "prdataset.jsonl"
        with dataset_file.open("w") as f:
            f.write("invalid json\n")

        with pytest.raises(ValueError, match="Failed to parse JSON"):
            load_pr_dataset_entries(dataset_file)


class TestBuildPRReviewPrompt:
    def test_build_prompt_replaces_placeholders(self):
        """Test that placeholders are correctly replaced."""
        entry = PRDatasetEntry(
            name="Test PR",
            description="Test description",
            diff="test diff content",
            target_comments=[],
        )

        template = """Instructions:
PullRequestName:
{prname}
PullRequestDescription:
{prdescription}
PullRequestFilesContentDiff:
{diff}
End."""

        result = build_pr_review_prompt(entry, template)

        assert "Test PR" in result
        assert "Test description" in result
        assert "test diff content" in result
        assert "{prname}" not in result
        assert "{prdescription}" not in result
        assert "{diff}" not in result

    def test_build_prompt_with_special_characters(self):
        """Test prompt building with special characters."""
        entry = PRDatasetEntry(
            name="PR: Update & Fix {Issue}",
            description="Description with 'quotes' and \"double quotes\"",
            diff='diff with "special" chars',
            target_comments=[],
        )

        template = "Name: {prname}\nDesc: {prdescription}\nDiff: {diff}"

        result = build_pr_review_prompt(entry, template)

        assert "PR: Update & Fix {Issue}" in result
        assert "Description with 'quotes' and \"double quotes\"" in result
        assert 'diff with "special" chars' in result


class TestBuildPRSecurityReviewPrompt:
    @patch("bcbench.agent.pr_security_review_helper.load_instructions_template")
    def test_build_pr_security_review_prompt_with_default_path(self, mock_load):
        """Test building PR security review prompt with default path."""
        mock_load.return_value = "Instructions:\n{prname}\n{prdescription}\n{diff}"

        entry = PRDatasetEntry(
            name="Test PR",
            description="Test desc",
            diff="test diff",
            target_comments=[],
        )

        result = build_pr_security_review_prompt(entry)

        assert "Test PR" in result
        assert "Test desc" in result
        assert "test diff" in result
        mock_load.assert_called_once()

    def test_build_pr_security_review_prompt_with_custom_path(self, tmp_path):
        """Test building PR security review prompt with custom instructions path."""
        instructions_file = tmp_path / "custom_instructions.md"
        instructions_file.write_text("Custom: {prname}, {prdescription}, {diff}")

        entry = PRDatasetEntry(
            name="Test PR",
            description="Test desc",
            diff="test diff",
            target_comments=[],
        )

        result = build_pr_security_review_prompt(entry, instructions_path=instructions_file)

        assert "Custom: Test PR, Test desc, test diff" in result

    def test_build_pr_security_review_prompt_missing_file(self):
        """Test that missing instructions file raises error."""
        entry = PRDatasetEntry(name="Test", description="", diff="", target_comments=[])

        with pytest.raises(FileNotFoundError):
            build_pr_security_review_prompt(entry, instructions_path="/nonexistent/path.md")


class TestLoadPRDataset:
    @patch("bcbench.agent.pr_security_review_helper.load_pr_dataset_entries")
    def test_load_pr_dataset_default_path(self, mock_load):
        """Test loading PR dataset with default path."""
        mock_entries = [Mock(spec=PRDatasetEntry)]
        mock_load.return_value = mock_entries

        result = load_pr_dataset()

        assert result == mock_entries
        # Verify it was called with a path ending in prdataset.jsonl
        call_args = mock_load.call_args[0][0]
        assert str(call_args).endswith("prdataset.jsonl")

    @patch("bcbench.agent.pr_security_review_helper.load_pr_dataset_entries")
    def test_load_pr_dataset_custom_path(self, mock_load):
        """Test loading PR dataset with custom path."""
        mock_entries = [Mock(spec=PRDatasetEntry)]
        mock_load.return_value = mock_entries

        custom_path = Path("/custom/path/data.jsonl")
        result = load_pr_dataset(custom_path)

        assert result == mock_entries
        mock_load.assert_called_once_with(custom_path)
