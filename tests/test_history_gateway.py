import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from unittest.mock import Mock
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from bcbench.agent.shared.history_gateway import HistoryGateway, resolve_history_settings, start_history_gateway
from bcbench.dataset.dataset_entry import BaseDatasetEntry, BugFixEntry
from bcbench.exceptions import AgentError
from bcbench.types import EvaluationCategory, HistorySettings, InvestigationTrace

_MODULE = "bcbench.agent.shared.history_gateway"
_CUTOFF = "a" * 40
_COMMIT = "b" * 40
_INSTANCE = "microsoftInternal__NAV-123456"
_REPORT = f"# Historical change report\n\n## Commit {_COMMIT}\n\nCafé: historical reference data.\n"


@pytest.fixture(autouse=True)
def report_builder(monkeypatch):
    builder = Mock(return_value=_REPORT)
    monkeypatch.setattr(f"{_MODULE}.build_remote_report", builder)
    return builder


@pytest.fixture
def gateway_factory(tmp_path):
    gateways = []

    def create(settings=None, **kwargs):
        gateway = HistoryGateway(
            repo=kwargs.get("repo", "NAV"),
            cutoff=kwargs.get("cutoff", _CUTOFF),
            instance_id=kwargs.get("instance_id", _INSTANCE),
            output_dir=tmp_path,
            settings=settings if settings is not None else HistorySettings(enabled=True, max_commits=3, max_files=2, history_depth=17, max_requests=2),
        ).start()
        gateways.append(gateway)
        return gateway

    yield create
    for gateway in gateways:
        gateway.stop()


@pytest.fixture
def gateway(gateway_factory):
    return gateway_factory()


def _request(gateway, payload=None, *, method="POST", path=None, body=None, headers=None):
    url = urlsplit(gateway.base_url)
    connection = HTTPConnection(url.hostname, url.port, timeout=10)
    try:
        if body is None and payload is not None:
            body = json.dumps(payload).encode()
        connection.request(method, path if path is not None else f"{url.path}/mcp", body=body, headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        return response.status, dict(response.getheaders()), json.loads(data) if data else None
    finally:
        connection.close()


def _rpc(gateway, method, params=None):
    status, _, payload = _request(gateway, {"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}})
    assert status == 200
    assert payload["id"] == 7
    return payload


def _call(gateway, name, **arguments):
    return _rpc(gateway, "tools/call", {"name": name, "arguments": arguments})["result"]


def _initial(gateway):
    result = _call(gateway, "record_scope", stage="initial", files=["src/Initial.al"], note="Related to the reported behavior.")
    assert result["isError"] is False


def _entry(repo="microsoftInternal/NAV"):
    return BugFixEntry(
        instance_id=_INSTANCE,
        repo=repo,
        base_commit=_CUTOFF,
        patch="GOLD_PATCH_MUST_NOT_LEAK",
        test_patch="GOLD_TEST_PATCH_MUST_NOT_LEAK",
        created_at="2026-09-21",
        environment_setup_version="26.5",
        FAIL_TO_PASS=[{"codeunitID": 100, "functionName": ["TestSomething"]}],
    )


def test_http_lifecycle_is_stateless_and_never_fetches_eagerly(gateway, report_builder, tmp_path):
    initialized = _rpc(
        gateway,
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
    )["result"]
    assert initialized["protocolVersion"] == "2025-03-26"
    assert initialized["capabilities"] == {"tools": {}}
    status, headers, body = _request(gateway, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert status == 202
    assert body is None
    assert "Mcp-Session-Id" not in headers
    assert _rpc(gateway, "ping")["result"] == {}
    tools = _rpc(gateway, "tools/list")["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["record_scope", "get_history"]
    history_schema = tools[1]["inputSchema"]
    assert set(history_schema["properties"]) == {"files"}
    assert history_schema["required"] == ["files"]
    assert history_schema["additionalProperties"] is False
    assert "not observed file-read evidence" in tools[0]["description"]
    assert tools[0]["inputSchema"]["additionalProperties"] is False
    assert gateway.trace == InvestigationTrace()
    report_builder.assert_not_called()
    assert not (tmp_path / "history").exists()


@pytest.mark.parametrize("version", ["2024-11-05", "2025-06-18", "2025-11-25"])
def test_initialize_negotiates_supported_protocol(gateway, version):
    assert _rpc(gateway, "initialize", {"protocolVersion": version})["result"]["protocolVersion"] == version


def test_initialize_negotiates_unknown_protocol(gateway):
    assert _rpc(gateway, "initialize", {"protocolVersion": "unknown"})["result"]["protocolVersion"] == "2025-11-25"
    assert _rpc(gateway, "initialize", {"protocolVersion": []})["error"]["code"] == -32602


def test_history_pins_repository_commit_limits_and_persists_utf8(gateway, report_builder, tmp_path):
    _initial(gateway)
    result = _call(gateway, "get_history", files=["src\\Café.al", "./src/Café.al"])
    assert result == {"content": [{"type": "text", "text": _REPORT}], "isError": False}
    report_builder.assert_called_once_with(
        ["NAV"],
        {"NAV": _CUTOFF},
        {"NAV": ["src/Café.al"]},
        max_commits=3,
        history_depth=17,
        max_files=2,
    )
    query = gateway.trace.queries[0]
    assert query.files == ["src/Café.al"]
    assert query.commit_ids == [_COMMIT]
    assert query.elapsed_seconds >= 0
    assert query.error is None
    assert query.report_name == f"{_INSTANCE}-001.md"
    assert (tmp_path / "history" / query.report_name).read_bytes() == _REPORT.encode("utf-8")


def test_initial_scope_required_and_immutable(gateway, report_builder):
    assert _call(gateway, "get_history", files=["src/A.al"])["isError"]
    assert _call(gateway, "record_scope", stage="final", files=[])["isError"]
    assert _call(gateway, "record_scope", stage="initial", files=[])["isError"]
    first = {"stage": "initial", "files": ["src\\A.al"], "note": "Relevant implementation."}
    assert not _call(gateway, "record_scope", **first)["isError"]
    assert not _call(gateway, "record_scope", **{**first, "files": ["./src/A.al"]})["isError"]
    assert _call(gateway, "record_scope", **{**first, "files": ["src/B.al"]})["isError"]
    assert _call(gateway, "record_scope", **{**first, "note": "Changed justification."})["isError"]
    assert gateway.trace.initial_scope.files == ["src/A.al"]
    assert gateway.trace.initial_scope.note == "Relevant implementation."
    assert gateway.trace.queries == []
    report_builder.assert_not_called()


@pytest.mark.parametrize(
    "files",
    [
        [],
        [""],
        ["."],
        ["../secret.al"],
        ["src/../secret.al"],
        ["/absolute.al"],
        ["C:\\absolute.al"],
        ["src/"],
        ["src\\"],
        ["src/."],
        ["a\0b"],
        ["a\nb"],
        ["a\tb"],
        ["\\\\host\\file"],
        [123],
        "src/A.al",
        None,
    ],
)
def test_invalid_history_paths_never_reach_backend(gateway, report_builder, files):
    _initial(gateway)
    assert _call(gateway, "get_history", files=files)["isError"]
    assert gateway.trace.queries == []
    report_builder.assert_not_called()


@pytest.mark.parametrize("extra_key", ["repo", "cutoff", "output_dir", "max_commits", "max_files", "history_depth", "max_requests", "patch"])
@pytest.mark.parametrize("tool", ["get_history", "record_scope"])
def test_tool_overrides_are_rejected(gateway, report_builder, extra_key, tool):
    _initial(gateway)
    arguments = {"files": ["src/A.al"], extra_key: "override"}
    if tool == "record_scope":
        arguments["stage"] = "final"
    assert _call(gateway, tool, **arguments)["isError"]
    report_builder.assert_not_called()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"files": ["src/A.al"]},
        {"stage": "initial"},
        {"stage": "other", "files": []},
        {"stage": [], "files": []},
        {"stage": "initial", "files": ["src/A.al"], "note": None},
        {"stage": "initial", "files": ["src/A.al"], "note": "x" * 2001},
    ],
)
def test_scope_arguments_are_validated(gateway, arguments):
    assert _call(gateway, "record_scope", **arguments)["isError"]
    assert gateway.trace.initial_scope is None


def test_final_scope_can_be_empty_updated_and_invalidated_by_late_history(gateway, report_builder):
    _initial(gateway)
    assert not _call(gateway, "record_scope", stage="final", files=[])["isError"]
    assert gateway.trace.final_scope.files == []
    assert not _call(gateway, "record_scope", stage="final", files=["src/B.al"], note="Changed implementation.")["isError"]
    before_history = gateway.trace
    assert not _call(gateway, "get_history", files=["src/B.al"])["isError"]
    assert gateway.trace.final_scope is None
    assert before_history.final_scope.files == ["src/B.al"]
    assert before_history.queries == []
    assert not _call(gateway, "record_scope", stage="final", files=["src/B.al"])["isError"]
    report_builder.side_effect = RuntimeError("sensitive report content")
    assert _call(gateway, "get_history", files=["src/B.al"])["isError"]
    assert gateway.trace.final_scope is None


def test_trace_is_deep_snapshot(gateway):
    _initial(gateway)
    _call(gateway, "get_history", files=["src/A.al"])
    _call(gateway, "record_scope", stage="final", files=["src/B.al"])
    snapshot = gateway.trace
    snapshot.initial_scope.files.append("injected.al")
    snapshot.final_scope.files.clear()
    snapshot.queries[0].files.clear()
    snapshot.queries[0].commit_ids.clear()
    snapshot.queries.clear()
    assert gateway.trace.initial_scope.files == ["src/Initial.al"]
    assert gateway.trace.final_scope.files == ["src/B.al"]
    assert gateway.trace.queries[0].files == ["src/A.al"]
    assert gateway.trace.queries[0].commit_ids == [_COMMIT]


def test_backend_errors_are_explicit_safe_recorded_and_consume_budget(gateway_factory, report_builder, monkeypatch, tmp_path):
    gateway = gateway_factory(settings=HistorySettings(enabled=True, max_requests=1))
    _initial(gateway)
    logger = Mock()
    monkeypatch.setattr(f"{_MODULE}.logger", logger)
    report_builder.side_effect = RuntimeError("password=secret; private historical report")
    result = _call(gateway, "get_history", files=["src/A.al"])
    assert result["isError"] is True
    assert result["content"][0]["text"] == "History request failed (RuntimeError)."
    query = gateway.trace.queries[0]
    assert query.files == ["src/A.al"]
    assert query.error == "History request failed (RuntimeError)."
    assert query.report_name is None
    assert query.commit_ids == []
    assert query.elapsed_seconds >= 0
    logger.error.assert_called_once_with("History request %d failed (%s)", 1, "RuntimeError")
    assert "secret" not in gateway.trace.model_dump_json()
    assert not (tmp_path / "history").exists()
    assert _call(gateway, "get_history", files=["src/B.al"])["isError"]
    report_builder.assert_called_once()
    assert len(gateway.trace.queries) == 1


def test_successes_also_consume_request_budget(gateway, report_builder):
    _initial(gateway)
    assert not _call(gateway, "get_history", files=["src/A.al"])["isError"]
    assert not _call(gateway, "get_history", files=["src/B.al"])["isError"]
    assert _call(gateway, "get_history", files=["src/C.al"])["isError"]
    assert report_builder.call_count == 2
    assert len(gateway.trace.queries) == 2


def test_file_write_failure_is_recorded(gateway, tmp_path, monkeypatch):
    _initial(gateway)
    (tmp_path / "history").write_text("not a directory", encoding="utf-8")
    logger = Mock()
    monkeypatch.setattr(f"{_MODULE}.logger", logger)
    assert _call(gateway, "get_history", files=["src/A.al"])["isError"]
    query = gateway.trace.queries[0]
    assert query.report_name is None
    assert query.error == "History request failed (FileExistsError)."
    assert query.commit_ids == [_COMMIT]
    logger.error.assert_called_once()


def test_reports_never_overwrite_existing_files_across_gateway_instances(gateway_factory, tmp_path):
    directory = tmp_path / "history"
    directory.mkdir()
    old = directory / f"{_INSTANCE}-001.md"
    old.write_text("previous report", encoding="utf-8")
    first = gateway_factory()
    _initial(first)
    _call(first, "get_history", files=["src/A.al"])
    second = gateway_factory()
    _initial(second)
    _call(second, "get_history", files=["src/A.al"])
    assert first.trace.queries[0].report_name == f"{_INSTANCE}-002.md"
    assert second.trace.queries[0].report_name == f"{_INSTANCE}-003.md"
    assert old.read_text(encoding="utf-8") == "previous report"


def test_commit_ids_require_exact_report_headings(gateway, report_builder):
    report_builder.return_value = f"## Commit {_COMMIT}\n## Commit {'C' * 40}\n## Commit {_COMMIT}\n## Commit short\ntext ## Commit {'d' * 40}\n## Commit {'e' * 41}\n"
    _initial(gateway)
    _call(gateway, "get_history", files=["src/A.al"])
    assert gateway.trace.queries[0].commit_ids == [_COMMIT, "C" * 40]


def test_baseline_exposes_only_agent_reported_scope(gateway_factory, report_builder, tmp_path):
    gateway = gateway_factory(settings=HistorySettings(measure_scope=True))
    tools = _rpc(gateway, "tools/list")["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["record_scope"]
    _initial(gateway)
    result = _call(gateway, "record_scope", stage="final", files=[])
    assert "agent-reported scope" in result["content"][0]["text"]
    response = _rpc(gateway, "tools/call", {"name": "get_history", "arguments": {"files": ["src/A.al"]}})
    assert response["error"]["code"] == -32602
    assert gateway.trace.final_scope.files == []
    assert gateway.trace.queries == []
    assert not (tmp_path / "history").exists()
    report_builder.assert_not_called()


@pytest.mark.parametrize("category", [category for category in EvaluationCategory if category not in (EvaluationCategory.BUG_FIX, EvaluationCategory.TEST_GENERATION)])
def test_other_categories_ignore_even_malformed_history_configuration(category):
    assert resolve_history_settings({"history": "malformed"}, category) is None


@pytest.mark.parametrize("category", [EvaluationCategory.BUG_FIX, EvaluationCategory.TEST_GENERATION])
def test_resolve_settings(category):
    assert resolve_history_settings({}, category) is None
    assert resolve_history_settings({"history": {"enabled": False, "measure_scope": False}}, category) is None
    settings = resolve_history_settings({"history": {"enabled": True, "measure_scope": False, "max_requests": 3}}, category)
    assert settings.enabled
    assert settings.measure_scope
    assert settings.max_requests == 3
    baseline = resolve_history_settings({"history": {"measure_scope": True}}, category)
    assert baseline.measure_scope
    assert not baseline.enabled


@pytest.mark.parametrize("history", [None, "invalid", {"max_requests": 0}, {"max_commits": -1}, {"history_depth": 0}, {"max_files": 0}])
def test_malformed_settings_surface_validation_error(history):
    with pytest.raises((ValidationError, AgentError)):
        resolve_history_settings({"history": history}, EvaluationCategory.BUG_FIX)


@pytest.mark.parametrize(("repo", "label"), [("microsoftInternal/NAV", "NAV"), ("MICROSOFTINTERNAL/nav", "NAV"), ("microsoft/BCApps", "BCApps"), ("MICROSOFT/bcapps", "BCApps")])
def test_entry_mapping_pins_metadata_without_retaining_gold(repo, label, tmp_path, report_builder):
    entry = _entry(repo)
    gateway = start_history_gateway(entry, HistorySettings(enabled=True), tmp_path)
    try:
        assert gateway is not None
        assert entry not in vars(gateway).values()
        assert "GOLD_PATCH_MUST_NOT_LEAK" not in repr(vars(gateway))
        assert "GOLD_TEST_PATCH_MUST_NOT_LEAK" not in repr(vars(gateway))
        _initial(gateway)
        _call(gateway, "get_history", files=["src/A.al"])
        report_builder.assert_called_once_with([label], {label: _CUTOFF}, {label: ["src/A.al"]}, max_commits=5, history_depth=200, max_files=10)
    finally:
        if gateway is not None:
            gateway.stop()


def test_disabled_start_ignores_entry_and_does_not_create_files(tmp_path):
    assert start_history_gateway(_entry("other/repository"), None, tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_unsupported_repository_is_rejected(tmp_path):
    with pytest.raises(AgentError, match="supports only"):
        start_history_gateway(_entry("other/repository"), HistorySettings(measure_scope=True), tmp_path)


def test_non_repository_entry_is_rejected(tmp_path):
    entry = Mock(spec=BaseDatasetEntry)
    with pytest.raises(AgentError, match="repository-grounded"):
        start_history_gateway(entry, HistorySettings(enabled=True), tmp_path)


@pytest.mark.parametrize("overrides", [{"repo": "other"}, {"cutoff": "HEAD"}, {"instance_id": "../escape"}, {"instance_id": "C:\\escape"}])
def test_constructor_rejects_unpinned_or_unsafe_metadata(gateway_factory, overrides):
    with pytest.raises(AgentError):
        gateway_factory(**overrides)


def test_concurrent_history_reserves_budget_and_blocks_final_scope(gateway_factory, report_builder):
    gateway = gateway_factory(settings=HistorySettings(enabled=True, max_requests=1))
    _initial(gateway)
    entered = threading.Event()
    release = threading.Event()

    def build(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return _REPORT

    report_builder.side_effect = build
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(_call, gateway, "get_history", files=["src/A.al"])
        try:
            assert entered.wait(5)
            assert _call(gateway, "record_scope", stage="final", files=[])["isError"]
            assert _call(gateway, "get_history", files=["src/B.al"])["isError"]
        finally:
            release.set()
        assert not pending.result(timeout=5)["isError"]
    assert not _call(gateway, "record_scope", stage="final", files=[])["isError"]
    report_builder.assert_called_once()


def test_stop_waits_for_inflight_telemetry_and_closes_listener(gateway, report_builder, monkeypatch):
    _initial(gateway)
    entered = threading.Event()
    release = threading.Event()
    stopping = threading.Event()
    url = urlsplit(gateway.base_url)
    original_shutdown = gateway._server.shutdown

    def shutdown():
        stopping.set()
        original_shutdown()

    def build(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return _REPORT

    monkeypatch.setattr(gateway._server, "shutdown", shutdown)
    report_builder.side_effect = build
    with ThreadPoolExecutor(max_workers=2) as executor:
        pending = executor.submit(_call, gateway, "get_history", files=["src/A.al"])
        try:
            assert entered.wait(5)
            stopped = executor.submit(gateway.stop)
            assert stopping.wait(5)
            assert not stopped.done()
        finally:
            release.set()
        assert not pending.result(timeout=5)["isError"]
        stopped.result(timeout=5)
    snapshot = gateway.trace
    assert len(snapshot.queries) == 1
    assert snapshot.queries[0].report_name
    assert gateway._server is None
    assert gateway._thread is None
    gateway.stop()
    assert gateway.trace == snapshot
    connection = HTTPConnection(url.hostname, url.port, timeout=1)
    try:
        with pytest.raises((ConnectionRefusedError, TimeoutError)):
            connection.connect()
    finally:
        connection.close()


def test_gateway_instances_have_distinct_loopback_paths_and_one_shot_lifecycle(gateway, gateway_factory):
    other = gateway_factory()
    assert gateway.base_url.startswith("http://127.0.0.1:")
    assert urlsplit(gateway.base_url).path != urlsplit(other.base_url).path
    assert not gateway.base_url.endswith("/mcp")
    assert gateway.start() is gateway
    gateway.stop()
    with pytest.raises(AgentError, match="cannot be restarted"):
        gateway.start()


@pytest.mark.parametrize("suffix", ["", "/mcp/child", "/mcpsomething", "/mcp?repo=other", "/../mcp"])
def test_unknown_paths_never_dispatch(gateway, report_builder, suffix):
    path = urlsplit(gateway.base_url).path + suffix
    status, _, _ = _request(gateway, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_history", "arguments": {"files": ["src/A.al"]}}}, path=path)
    assert status == 404
    report_builder.assert_not_called()


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_unsupported_http_methods_do_not_dispatch(gateway, report_builder, method):
    status, headers, _ = _request(gateway, method=method)
    assert status == 405
    assert headers["Allow"] == "POST"
    report_builder.assert_not_called()


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ([], -32600),
        ({}, -32600),
        ({"jsonrpc": "1.0", "method": "ping", "id": 1}, -32600),
        ({"jsonrpc": "2.0", "method": [], "id": 1}, -32600),
        ({"jsonrpc": "2.0", "method": "ping", "id": True}, -32600),
        ({"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "get_history", "arguments": {"files": ["src/A.al"]}}}, -32600),
        ({"jsonrpc": "2.0", "method": "tools/list", "params": [], "id": 1}, -32602),
        ({"jsonrpc": "2.0", "method": "unknown", "id": 1}, -32601),
    ],
)
def test_protocol_errors_do_not_reach_backend(gateway, report_builder, payload, code):
    _, _, response = _request(gateway, payload)
    assert response["error"]["code"] == code
    report_builder.assert_not_called()


@pytest.mark.parametrize("params", [{"name": "unknown"}, {"name": ["get_history"]}, {"name": "get_history", "arguments": []}, {"name": "get_history", "arguments": None}])
def test_unknown_tools_and_malformed_arguments(gateway, report_builder, params):
    assert _rpc(gateway, "tools/call", params)["error"]["code"] == -32602
    report_builder.assert_not_called()


@pytest.mark.parametrize("body", [b"{", b"\xff", b"null"])
def test_malformed_json(gateway, report_builder, body):
    status, _, response = _request(gateway, body=body)
    assert status == 400
    assert "error" in response
    report_builder.assert_not_called()


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        ({"Content-Length": "invalid"}, b"{}", 400),
        ({"Content-Length": "-1"}, b"{}", 400),
        ({}, b"", 400),
        ({"Content-Length": "65537"}, b"{}", 413),
        ({"Transfer-Encoding": "chunked"}, b"{}", 400),
        ({"Content-Type": "text/plain"}, b"{}", 415),
        ({"Origin": "https://untrusted.invalid"}, b"{}", 403),
    ],
)
def test_http_framing_and_origin_errors(gateway, report_builder, headers, body, status):
    assert _request(gateway, body=body, headers=headers)[0] == status
    report_builder.assert_not_called()


def test_incomplete_request_body_times_out_without_dispatch(gateway, report_builder, monkeypatch):
    monkeypatch.setattr(f"{_MODULE}._REQUEST_TIMEOUT_SECONDS", 0.05)
    status, _, response = _request(gateway, body=b"{}", headers={"Content-Length": "100"})
    assert status == 400
    assert response["error"]["code"] == -32600
    report_builder.assert_not_called()
