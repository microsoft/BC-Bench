import json
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from bcbench.cli import app
from tests.test_harms import case, write_jsonl
from tests.test_harms import config as capture_config

config = capture_config


@pytest.mark.parametrize(("group", "command"), [("harms", "run"), ("redteam", "run"), ("redteam", "scan")])
def test_aliases_run_the_same_private_capture_without_sdk(tmp_path, config, monkeypatch, group, command):
    monkeypatch.setattr("bcbench.commands.harms.os", SimpleNamespace(name="nt"))
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(config.model_dump_json(), encoding="utf-8")
    write_jsonl(tmp_path / "cases.jsonl", [case().model_dump()])
    calls = []

    def capture(*args):
        calls.append(args)
        assert all(path.is_absolute() for path in (args[0], *args[2:]))

    monkeypatch.setattr("bcbench.commands.harms.run_capture", capture)
    result = CliRunner().invoke(
        app,
        [
            group,
            command,
            "--source",
            "manual",
            "--capture-only",
            "--config",
            "config.json",
            "--cases",
            "cases.jsonl",
            "--symbols",
            ".",
            "--bcal",
            "config.json",
            "--bridge-python",
            "config.json",
            "--output",
            "out",
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert json.loads((tmp_path / "out" / "summary.json").read_text())["status"] == "capture_only"


@pytest.mark.parametrize("group", ["harms", "redteam"])
def test_aliases_reject_private_fields_in_shared_summary(tmp_path, group):
    (tmp_path / "summary.json").write_text('{"prompt": "private-sentinel"}')
    result = CliRunner().invoke(app, [group, "publish-summary", "--output", str(tmp_path), "--destination", str(tmp_path / "shared")])
    assert result.exit_code == 1
    assert "private-sentinel" not in result.output
    assert not (tmp_path / "shared").exists()
