"""Tests for setup_repo_prebuild and related setup operations."""

from unittest.mock import MagicMock, patch

from bcbench.operations.setup_operations import setup_repo_prebuild
from tests.conftest import create_dataset_entry


class TestSetupRepoPrebuild:
    def test_skips_when_no_base_commit(self, tmp_path):
        mock_entry = MagicMock()
        mock_entry.base_commit = ""
        mock_entry.instance_id = "test__entry-001"

        with patch("bcbench.operations.setup_operations.clean_repo") as mock_clean, patch("bcbench.operations.setup_operations.checkout_commit") as mock_checkout:
            setup_repo_prebuild(mock_entry, tmp_path)

        mock_clean.assert_not_called()
        mock_checkout.assert_not_called()

    def test_calls_clean_repo_when_base_commit_set(self, tmp_path):
        entry = create_dataset_entry()
        assert entry.base_commit  # Confirm it has a base_commit

        with patch("bcbench.operations.setup_operations.clean_repo") as mock_clean, patch("bcbench.operations.setup_operations.checkout_commit") as _:
            setup_repo_prebuild(entry, tmp_path)

        mock_clean.assert_called_once_with(tmp_path)

    def test_calls_checkout_commit_with_correct_args(self, tmp_path):
        entry = create_dataset_entry()

        with patch("bcbench.operations.setup_operations.clean_repo"), patch("bcbench.operations.setup_operations.checkout_commit") as mock_checkout:
            setup_repo_prebuild(entry, tmp_path)

        mock_checkout.assert_called_once_with(tmp_path, entry.base_commit)

    def test_clean_called_before_checkout(self, tmp_path):
        entry = create_dataset_entry()
        call_order = []

        with (
            patch("bcbench.operations.setup_operations.clean_repo", side_effect=lambda *a: call_order.append("clean")),
            patch("bcbench.operations.setup_operations.checkout_commit", side_effect=lambda *a: call_order.append("checkout")),
        ):
            setup_repo_prebuild(entry, tmp_path)

        assert call_order == ["clean", "checkout"]
