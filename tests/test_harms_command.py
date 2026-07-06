"""CLI wiring tests for the `bcbench harms` command group."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from bcbench.cli import app
from bcbench.harms.case import HarmsVector
from bcbench.harms.runner import HarmsTrial

runner = CliRunner()


def _trial() -> HarmsTrial:
    return HarmsTrial(
        case_id="c1",
        vector=HarmsVector.DIRECT,
        channel=HarmsVector.DIRECT.channel,
        risk="code_vulnerability",
        attack="do a bad thing",
        prompt="do a bad thing",
        response="out",
        executed=True,
        fixture_path=None,
        export_dir="e",
        log_path=None,
    )


_SUITE = """
cases:
  - id: c1
    page: "Customer Card"
    harm: "do a bad thing"
    trigger: "add a benign field"
"""


def _suite(tmp_path: Path) -> Path:
    path = tmp_path / "s.harms.yaml"
    path.write_text(_SUITE, encoding="utf-8")
    return path


def test_harms_is_registered():
    result = runner.invoke(app, ["harms", "--help"])
    assert result.exit_code == 0
    assert "run" in result.output
    assert "report" in result.output


def test_dry_run_skips_evaluate(tmp_path: Path):
    with (
        patch("bcbench.commands.harms.run_harms_suite", return_value=[]) as mock_run,
        patch("bcbench.commands.harms.evaluate_trials") as mock_eval,
    ):
        result = runner.invoke(app, ["harms", "run", "--dry-run", "--suite", str(_suite(tmp_path)), "--results-dir", str(tmp_path / "out")])

    assert result.exit_code == 0, result.output
    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["dry_run"] is True
    mock_eval.assert_not_called()


def test_missing_foundry_project_without_dry_run_fails(tmp_path: Path, monkeypatch):
    # Ensure no Foundry env vars leak in from the ambient environment.
    for var in ("AZURE_SUBSCRIPTION_ID", "AZURE_RESOURCE_GROUP", "AZURE_PROJECT_NAME"):
        monkeypatch.delenv(var, raising=False)

    result = runner.invoke(app, ["harms", "run", "--suite", str(_suite(tmp_path)), "--results-dir", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "Foundry project" in result.output


def test_full_run_invokes_evaluate_with_upload(tmp_path: Path):
    with (
        patch("bcbench.commands.harms.run_harms_suite", return_value=[_trial()]),
        patch("bcbench.commands.harms.evaluate_trials", return_value={"metrics": {"content_safety.violence": 0.0}, "rows": []}) as mock_eval,
    ):
        result = runner.invoke(
            app,
            [
                "harms",
                "run",
                "--suite",
                str(_suite(tmp_path)),
                "--results-dir",
                str(tmp_path / "out"),
                "--subscription-id",
                "s",
                "--resource-group",
                "rg",
                "--project-name",
                "p",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_eval.assert_called_once()
    assert mock_eval.call_args.kwargs["upload"] is True
    assert mock_eval.call_args.args[1] == {"subscription_id": "s", "resource_group_name": "rg", "project_name": "p"}


def test_no_upload_flag_disables_upload(tmp_path: Path):
    with (
        patch("bcbench.commands.harms.run_harms_suite", return_value=[_trial()]),
        patch("bcbench.commands.harms.evaluate_trials", return_value={"metrics": {"content_safety.violence": 0.0}, "rows": []}) as mock_eval,
    ):
        result = runner.invoke(
            app,
            [
                "harms",
                "run",
                "--suite",
                str(_suite(tmp_path)),
                "--results-dir",
                str(tmp_path / "out"),
                "--no-upload",
                "--subscription-id",
                "s",
                "--resource-group",
                "rg",
                "--project-name",
                "p",
            ],
        )

    assert result.exit_code == 0, result.output
    assert mock_eval.call_args.kwargs["upload"] is False
