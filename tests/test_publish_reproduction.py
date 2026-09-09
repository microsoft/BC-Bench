import importlib.util
import io
import json
import sys
from pathlib import Path
from queue import Empty, Queue
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_probe():
    path = ROOT / "tools" / "reproduce_al_publish.py"
    assert path.is_file(), "The publishing diagnostic has not been implemented"
    spec = importlib.util.spec_from_file_location("reproduce_al_publish", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_redacts_credentials_without_replacing_empty_strings():
    probe = load_probe()
    assert probe.redact("password=secret; token=secret-long", ("", "secret", "secret-long")) == "password=***; token=***"


def test_saved_patch_requires_the_expected_entry(tmp_path):
    probe = load_probe()
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps({"instance_id": "wrong", "output": "diff"}))
    with pytest.raises(ValueError, match="instance"):
        probe.read_saved_patch(path)


@pytest.mark.parametrize("contents", ["", "{}\n{}\n", '{"instance_id":"microsoftInternal__NAV-223493","output":""}'])
def test_saved_patch_rejects_missing_or_ambiguous_output(tmp_path, contents):
    probe = load_probe()
    path = tmp_path / "result.jsonl"
    path.write_text(contents)
    with pytest.raises(ValueError, match=r"saved result|generated patch"):
        probe.read_saved_patch(path)


def test_saved_patch_returns_original_output(tmp_path):
    probe = load_probe()
    path = tmp_path / "result.jsonl"
    path.write_text(json.dumps({"instance_id": probe.INSTANCE_ID, "output": "original patch"}))
    assert probe.read_saved_patch(path) == "original patch"


def test_response_reader_ignores_notifications():
    probe = load_probe()
    messages = Queue()
    messages.put('{"jsonrpc":"2.0","method":"notifications/message","params":{}}')
    messages.put('{"jsonrpc":"2.0","id":7,"result":{"isError":false}}')
    assert probe.read_response(messages, 7, 1) == {"jsonrpc": "2.0", "id": 7, "result": {"isError": False}}


def test_response_reader_detects_closed_transport():
    probe = load_probe()
    messages = Queue()
    messages.put(None)
    with pytest.raises(RuntimeError, match="closed"):
        probe.read_response(messages, 7, 1)


def test_response_reader_enforces_deadline_even_with_queued_messages(monkeypatch):
    probe = load_probe()
    times = iter([0, 2, 3])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(times))
    messages = Queue()
    messages.put('{"jsonrpc":"2.0","method":"notifications/message"}')
    messages.put('{"jsonrpc":"2.0","id":7,"result":{}}')
    with pytest.raises(Empty):
        probe.read_response(messages, 7, 1)


def test_timed_out_request_sends_cancellation(tmp_path):
    probe = load_probe()
    transport = SimpleNamespace(stdin=io.StringIO())
    messages = Queue()
    evidence = probe.Evidence(tmp_path, ())
    result = probe.request(transport, messages, evidence, 4, "tools/call", {"name": "al_publish"}, timeout=0.001)
    sent = [json.loads(line) for line in transport.stdin.getvalue().splitlines()]
    assert result is None
    assert sent[-1]["method"] == "notifications/cancelled"
    assert sent[-1]["params"]["requestId"] == 4
    assert evidence.records[-1]["timed_out"] is True


def test_request_detects_failure_inside_an_al_tool_result(tmp_path):
    probe = load_probe()
    transport = SimpleNamespace(stdin=io.StringIO())
    messages = Queue()
    messages.put(json.dumps({"jsonrpc": "2.0", "id": 4, "result": {"content": [{"type": "text", "text": json.dumps({"succeeded": False, "message": "Publish failed"})}]}}))
    evidence = probe.Evidence(tmp_path, ())
    assert probe.request(transport, messages, evidence, 4, "tools/call", {"name": "al_publish"}) is None
    assert evidence.records[-1]["returncode"] == 1


def test_replay_budget_matches_baseapp_operations():
    probe = load_probe()
    assert probe.get_config().timeout.build_baseapp == probe.MCP_TIMEOUT


def test_evidence_redacts_streams_and_records_failure(tmp_path):
    probe = load_probe()
    evidence = probe.Evidence(tmp_path, ("secret",))
    evidence.record("publish", 1, 0.5, "stdout secret", "stderr secret")
    assert "secret" not in (tmp_path / "publish.stdout.log").read_text()
    assert "secret" not in (tmp_path / "publish.stderr.log").read_text()
    assert json.loads((tmp_path / "summary.json").read_text())[-1]["returncode"] == 1


def test_replay_stops_mcp_before_applying_hidden_tests(monkeypatch, tmp_path):
    probe = load_probe()
    events = []
    entry = SimpleNamespace(project_paths=["app", "test"], test_patch="hidden")
    monkeypatch.setattr(probe, "snapshot", lambda *args: events.append("snapshot"))
    monkeypatch.setattr(probe, "run_al_mcp", lambda *args: events.append("mcp-finished") or False)
    monkeypatch.setattr(probe, "categorize_projects", lambda paths: (["test"], ["app"]))
    monkeypatch.setattr(probe, "clean_project_paths", lambda *args: events.append("clean-tests"))
    monkeypatch.setattr(probe, "apply_patch", lambda repo, patch, name: events.append(patch))
    monkeypatch.setattr(probe, "build_projects", lambda *args: events.append("evaluator-publish") or True)
    assert probe.replay(entry, tmp_path, None, "generated", None) is False
    assert events == ["generated", "snapshot", "mcp-finished", "snapshot", "clean-tests", "hidden", "evaluator-publish", "snapshot"]


def test_diagnostic_refuses_non_ci_workspace(monkeypatch, tmp_path):
    probe = load_probe()
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(ValueError, match="disposable"):
        probe.require_disposable_workspace(tmp_path, "bcbench-223493")


def test_mcp_session_records_responses_and_exits_cleanly(monkeypatch, tmp_path):
    probe = load_probe()
    server = """
import json
import sys
for line in sys.stdin:
    message = json.loads(line)
    if "id" in message:
        print(json.dumps({"jsonrpc":"2.0", "id":message["id"], "result":{}}), flush=True)
"""
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(probe, "get_config", lambda: SimpleNamespace(paths=SimpleNamespace(agent_share_dir=tmp_path)))
    configuration = json.dumps({"mcpServers": {"altool": {"command": sys.executable, "args": ["-u", "-c", server]}}})
    monkeypatch.setattr(probe, "build_mcp_config", lambda *args, **kwargs: (configuration, ["altool"]))
    monkeypatch.setattr(probe, "categorize_projects", lambda paths: ([], ["app"]))
    evidence = probe.Evidence(tmp_path / "logs", ())
    entry = SimpleNamespace(project_paths=["app"])
    container = probe.ContainerConfig("test", "admin", "secret", "CRONUS")
    deadlines = []
    read_response = probe.read_response

    def record_deadline(messages, request_id, timeout):
        deadlines.append(timeout)
        return read_response(messages, request_id, timeout)

    monkeypatch.setattr(probe, "read_response", record_deadline)
    assert probe.run_al_mcp(entry, tmp_path, container, evidence)
    assert deadlines == [180, 180, 1800, 1800]
    assert evidence.records[-1]["phase"] == "mcp-shutdown"
    assert evidence.records[-1]["returncode"] == 0
    publish = json.loads((evidence.root / "mcp-4-al_publish.request.json").read_text())
    assert publish["params"]["arguments"]["skipBuild"] is True


def test_workflow_runs_one_branch_scoped_job_without_an_agent():
    path = ROOT / ".github" / "workflows" / "reproduce-al-publish.yml"
    assert path.is_file(), "The one-shot diagnostic workflow has not been implemented"
    text = path.read_text()
    workflow = yaml.safe_load(text)
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"push"}
    assert triggers["push"]["branches"] == ["private/ventselartur/publish-repro-34091156251"]
    assert len(workflow["jobs"]) == 1
    job = next(iter(workflow["jobs"].values()))
    assert job["timeout-minutes"] <= 120
    assert "strategy" not in job
    for step in job["steps"]:
        if ".github/actions/" in step.get("uses", ""):
            assert step["uses"].startswith("./")
    upload = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()"
    assert "34091156251" in text
    assert "microsoftInternal__NAV-223493" in text
    assert "evaluate claude" not in text
    assert "evaluate copilot" not in text
    assert "summarize-results" not in text
