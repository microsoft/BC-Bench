import io
import json
import runpy
import sys
from pathlib import Path

import pytest

HOOK_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "bcbench" / "agent" / "shared" / "hooks" / "log_tool_usage.py"


def _run_hook(stdin_payload: str, monkeypatch: pytest.MonkeyPatch, tool_log: Path) -> None:
    monkeypatch.setenv("BCBENCH_TOOL_LOG", str(tool_log))
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(HOOK_SCRIPT), run_name="__main__")
    assert exc.value.code == 0


def test_hook_writes_tool_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    _run_hook(json.dumps({"tool_name": "view", "timestamp": "2026-01-01T00:00:00Z"}), monkeypatch, tool_log)
    lines = tool_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {"tool_name": "view", "timestamp": "2026-01-01T00:00:00Z"}


def test_hook_accepts_camelcase_tool_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    _run_hook(json.dumps({"toolName": "edit"}), monkeypatch, tool_log)
    assert json.loads(tool_log.read_text(encoding="utf-8").strip())["tool_name"] == "edit"


def test_hook_expands_lsp_with_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    payload = {"tool_name": "lsp", "toolArgs": {"operation": "findReferences"}}
    _run_hook(json.dumps(payload), monkeypatch, tool_log)
    assert json.loads(tool_log.read_text(encoding="utf-8").strip())["tool_name"] == "lsp:findReferences"


def test_hook_accepts_lsp_args_as_json_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    payload = {"tool_name": "lsp", "tool_input": json.dumps({"operation": "hover"})}
    _run_hook(json.dumps(payload), monkeypatch, tool_log)
    assert json.loads(tool_log.read_text(encoding="utf-8").strip())["tool_name"] == "lsp:hover"


def test_hook_lsp_without_operation_keeps_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    _run_hook(json.dumps({"tool_name": "lsp"}), monkeypatch, tool_log)
    assert json.loads(tool_log.read_text(encoding="utf-8").strip())["tool_name"] == "lsp"


def test_hook_no_tool_name_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    _run_hook(json.dumps({"other_field": "x"}), monkeypatch, tool_log)
    assert not tool_log.exists()


def test_hook_missing_env_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    monkeypatch.delenv("BCBENCH_TOOL_LOG", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"tool_name": "view"})))
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(HOOK_SCRIPT), run_name="__main__")
    assert exc.value.code == 0
    assert not tool_log.exists()


def test_hook_malformed_stdin_does_not_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tool_log = tmp_path / "tool_usage.jsonl"
    _run_hook("not valid json", monkeypatch, tool_log)
    assert not tool_log.exists()
