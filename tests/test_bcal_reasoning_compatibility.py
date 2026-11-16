import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("compatibility", Path(__file__).parents[1] / "scripts" / "bcal_reasoning_compatibility.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("location", ["installed", "cache"])
def test_discovers_exact_archive_in_both_installer_locations(tmp_path, monkeypatch, location):
    root = tmp_path / "installed"
    binary = root / "tools" / "net10.0" / "any" / "bcal.dll"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"synthetic binary")
    cache = tmp_path / "cache"
    cache.mkdir()
    folder = root if location == "installed" else cache
    archive = folder / "microsoft.businesscentral.bcal.cli.30.0.46.49019-beta.nupkg"
    archive.write_bytes(b"synthetic exact archive")
    monkeypatch.setattr(module, "PACKAGE_SHA", hashlib.sha256(archive.read_bytes()).hexdigest())
    assert module.discover_package(root, cache) == (binary.parent, archive)


@pytest.mark.parametrize("failure", ["wrong_archive", "missing_archive", "missing_binary"])
def test_package_discovery_fails_closed(tmp_path, failure):
    root = tmp_path / "installed"
    binary = root / "tools" / "net10.0" / "any" / "bcal.dll"
    binary.parent.mkdir(parents=True)
    if failure != "missing_binary":
        binary.write_bytes(b"synthetic binary")
    if failure != "missing_archive":
        (root / "microsoft.businesscentral.bcal.cli.30.0.46.49019-beta.nupkg").write_bytes(b"wrong archive")
    with pytest.raises(module.AdmissionError):
        module.discover_package(root, tmp_path / "cache")


def test_effort_distinguishes_omission_none_and_null():
    assert module.effort({}, "responses") == {"presence": "omitted"}
    assert module.effort({"reasoning": {"effort": "none"}}, "responses") == {"presence": "explicit", "value": "none"}
    assert module.effort({"reasoning_effort": None}, "chat-completions") == {"presence": "null", "value": None}


def test_budget_blocks_retry_after429_and_counts_transport_failures(tmp_path):
    budget = module.AttemptBudget(tmp_path / "attempts.json")
    sent = []

    def send():
        sent.append(True)
        return SimpleNamespace(status_code=429)

    assert budget.send("cell", send).status_code == 429
    with pytest.raises(module.AdmissionError):
        budget.send("cell", send)
    assert len(sent) == 1
    with pytest.raises(ConnectionError):
        budget.send("transport", lambda: (_ for _ in ()).throw(ConnectionError()))
    assert budget.snapshot()["attempts"] == 2
    assert json.loads((tmp_path / "attempts.json").read_text())["events"][-1]["outcome"] == "transport_failure"


def test_global_budget_is_atomic_under_concurrent_sends(tmp_path):
    budget = module.AttemptBudget(tmp_path / "attempts.json")
    sent = []

    def attempt(index):
        try:
            budget.send(str(index), lambda: (sent.append(index), SimpleNamespace(status_code=200))[1])
        except module.AdmissionError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(40))) == 24
    assert len(sent) == 24
    assert budget.snapshot()["attempts"] == 24
    with pytest.raises(FileExistsError):
        module.AttemptBudget(tmp_path / "attempts.json")


def test_admission_rejects_effort_mismatch_and_real_tools():
    body = {"model": module.MODELS[0], "reasoning": {"effort": "medium"}, "parallel_tool_calls": False, "tools": [{"type": "function", **module.TOOL}]}
    expected = {"presence": "explicit", "value": "medium"}
    module.admit(body, module.MODELS[0], "responses", expected)
    with pytest.raises(module.AdmissionError):
        module.admit(body, module.MODELS[0], "responses", {"presence": "omitted"})
    body["tools"][0]["name"] = "compile"
    with pytest.raises(module.AdmissionError):
        module.admit(body, module.MODELS[0], "responses", expected)


def test_sse_receipt_retains_usage_without_content():
    response = {
        "type": "response.completed",
        "response": {
            "model": "safe-model",
            "status": "completed",
            "output": [{"type": "function_call", "arguments": '{"value":"private"}'}],
            "usage": {"output_tokens": 4, "output_tokens_details": {"reasoning_tokens": 2}},
        },
    }
    data = ("data: " + json.dumps(response) + "\n\ndata: [DONE]\n").encode()
    result = module.safe_response(200, data, True)
    assert result["responseSuccess"]
    assert result["reasoningTokens"] == 2
    assert result["toolArgumentsJsonValid"]
    assert "private" not in json.dumps(result)
    assert module.safe_response(429, b'{"error":{"message":"private"}}', False)["errorCategory"] == "quota_or_throttle"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "completed", "output": []},
        {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
    ],
)
def test_empty_provider_result_is_not_success(body):
    assert not module.safe_response(200, json.dumps(body).encode(), False)["responseSuccess"]
