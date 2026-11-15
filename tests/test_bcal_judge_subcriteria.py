import hashlib
import importlib
import json
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def diagnostics(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("bcal_judge_subcriteria")


@pytest.fixture
def contract():
    text = "PRIVATE compound requirement"
    job = {"input": "PRIVATE prompt", "output": "PRIVATE AL response", "expected": {"assertions": [{"text": text, "level": "critical"}]}}
    official = {"quality": 0.0, "testPassed": False, "assertionPass": [False]}
    specification = {
        "schemaVersion": 1,
        "parents": [
            {
                "assertionPosition1": 1,
                "assertionSha256": hashlib.sha256(text.encode()).hexdigest(),
                "subcriteria": [{"id": "insert-validation", "text": "PRIVATE insert requirement"}, {"id": "modify-validation", "text": "PRIVATE modify requirement"}],
            }
        ],
    }
    return job, official, specification


@pytest.mark.parametrize("mutation", ["parent", "position", "duplicate-id", "duplicate-text", "extra-field", "invalid-score", "invalid-parent-verdict", "boolean-position"])
def test_rejects_mismatched_or_ambiguous_subcriteria(diagnostics, contract, mutation):
    job, official, specification = contract
    parent = specification["parents"][0]
    if mutation == "parent":
        parent["assertionSha256"] = "0" * 64
    elif mutation == "position":
        parent["assertionPosition1"] = 2
    elif mutation == "boolean-position":
        parent["assertionPosition1"] = True
    elif mutation == "duplicate-id":
        parent["subcriteria"][1]["id"] = parent["subcriteria"][0]["id"]
    elif mutation == "duplicate-text":
        parent["subcriteria"][1]["text"] = parent["subcriteria"][0]["text"]
    elif mutation == "extra-field":
        parent["subcriteria"][0]["rawReasoning"] = "PRIVATE"
    elif mutation == "invalid-score":
        official["quality"] = 1.0
    else:
        official["testPassed"] = True
    with pytest.raises(ValueError, match="diagnostic evidence"):
        diagnostics.criteria_projection(job, official, specification)


def test_verified_source_range_keeps_only_hash_and_lines(diagnostics, contract, tmp_path):
    criteria = diagnostics.criteria_projection(*contract)
    source = b"PRIVATE AL first line\nPRIVATE AL second line\n"
    (tmp_path / "private.al").write_bytes(source)
    references = {
        "schemaVersion": 1,
        "criteria": [{"id": "insert-validation", "references": [{"path": "private.al", "sourceSha256": diagnostics.sha256(source), "startLine": 1, "endLine": 2}]}],
    }
    safe = diagnostics.reference_projection(criteria, references, tmp_path)
    assert safe["insert-validation"]["available"] is True
    assert safe["insert-validation"]["references"][0]["verification"] == "content-and-range-only"
    assert safe["modify-validation"] == {"available": False, "reason": "not-supplied", "references": []}
    assert "PRIVATE" not in json.dumps(safe)
    assert "private.al" not in json.dumps(safe)


def test_authored_catalog_binds_existing_tasks_and_parent_assertions(diagnostics):
    catalog = json.loads((ROOT / "experiments" / "bcal-judge-subcriteria" / "criteria.json").read_bytes())
    entries = {entry["instance_id"]: entry for entry in map(json.loads, (ROOT / "dataset" / "nl2al.jsonl").read_text(encoding="utf-8").splitlines())}
    assert len(catalog["cases"]) == 8
    total = 0
    for case in catalog["cases"]:
        entry = entries[case["instanceId"]]
        job = {"input": entry["nl_prompt"], "output": "private output", "expected": {"assertions": entry["expected"]}}
        official = {"quality": 1.0, "testPassed": True, "assertionPass": [True] * len(entry["expected"])}
        specification = diagnostics.select_specification(job, catalog, case["instanceId"])
        projected = diagnostics.criteria_projection(job, official, specification)
        assert all(item["officialParentPassed"] is True for item in projected)
        total += len(projected)
    assert total == 29


def test_catalog_rejects_wrong_task_or_duplicate_identity(diagnostics, contract):
    job, _, specification = contract
    catalog = {"schemaVersion": 1, "cases": [{"instanceId": "case", "inputSha256": diagnostics.sha256(job["input"].encode()), "parents": specification["parents"]}]}
    with pytest.raises(ValueError, match="diagnostic evidence"):
        diagnostics.select_specification({**job, "input": "different"}, catalog, "case")
    with pytest.raises(ValueError, match="diagnostic evidence"):
        diagnostics.select_specification(job, catalog, "absent")
    catalog["cases"].append(catalog["cases"][0])
    with pytest.raises(ValueError, match="diagnostic evidence"):
        diagnostics.select_specification(job, catalog, "case")


@pytest.mark.parametrize("mutation", ["traversal", "absolute", "hash", "line", "boolean-line", "unknown-id", "raw-field", "duplicate", "alternate-stream"])
def test_invalid_source_evidence_never_becomes_verified(diagnostics, contract, tmp_path, mutation):
    criteria = diagnostics.criteria_projection(*contract)
    source = b"PRIVATE\n"
    (tmp_path / "private.al").write_bytes(source)
    reference = {"path": "private.al", "sourceSha256": diagnostics.sha256(source), "startLine": 1, "endLine": 1}
    item = {"id": "insert-validation", "references": [reference]}
    evidence = {"schemaVersion": 1, "criteria": [item]}
    if mutation == "traversal":
        reference["path"] = "..\\private.al"
    elif mutation == "absolute":
        reference["path"] = str(tmp_path / "private.al")
    elif mutation == "hash":
        reference["sourceSha256"] = "0" * 64
    elif mutation == "line":
        reference["endLine"] = 2
    elif mutation == "boolean-line":
        reference["startLine"] = True
    elif mutation == "unknown-id":
        item["id"] = "unknown"
    elif mutation == "raw-field":
        reference["source"] = "PRIVATE"
    elif mutation == "duplicate":
        evidence["criteria"].append(item)
    else:
        reference["path"] = "private.al:stream"
    with pytest.raises(ValueError, match="diagnostic evidence"):
        diagnostics.reference_projection(criteria, evidence, tmp_path)


@pytest.mark.parametrize("failed", [False, True])
def test_separate_diagnostic_verdicts_preserve_official_scores_and_failure_semantics(diagnostics, contract, tmp_path, monkeypatch, failed):
    transport = importlib.import_module("bcal_study_transport")
    job, official, specification = contract
    for name, value in (("input", job), ("official", official), ("subcriteria", specification)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    before = (tmp_path / "official.json").read_bytes()
    error = subprocess.CalledProcessError(7, ["PRIVATE"])
    calls = []

    def judge(args):
        calls.append(json.loads(args.input.read_bytes()))
        transport.write_json(
            args.output.with_suffix(".diagnostics.json"),
            {"schemaVersion": 1, "events": [{"phase": "client", "outcome": "failed" if failed else "started", "category": "http_status", "httpStatus": 503, "body": "PRIVATE"}]},
        )
        if failed:
            raise error
        transport.write_json(args.output, {"quality": 0.5, "testPassed": False, "assertionPass": [True, False]})

    monkeypatch.setattr(transport, "judge", judge)
    args = Namespace(
        input=tmp_path / "input.json",
        official_output=tmp_path / "official.json",
        subcriteria=tmp_path / "subcriteria.json",
        source_references=None,
        source_root=None,
        output=tmp_path / "diagnostic.json",
    )
    if failed:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            diagnostics.run(args)
        assert caught.value is error
    else:
        diagnostics.run(args)
    result = json.loads(args.output.read_bytes())
    assert result["status"] == ("failed" if failed else "completed")
    assert [item["verdict"] for item in result["criteria"]] == (["unavailable", "unavailable"] if failed else ["pass", "fail"])
    assert all(item["officialParentPassed"] is False for item in result["criteria"])
    assert "quality" not in result
    assert "testPassed" not in result
    assert (tmp_path / "official.json").read_bytes() == before
    assert result["officialScoresSha256"] == diagnostics.sha256(before)
    assert result["judgeDiagnostics"]["valid"] is True
    assert all(not item["implementationEvidence"]["available"] for item in result["criteria"])
    assert "PRIVATE" not in json.dumps(result)
    assert len(calls) == 1
    assert calls[0]["expected"]["assertions"] == [{"text": item["text"], "level": "expected"} for item in specification["parents"][0]["subcriteria"]]
    assert not list(tmp_path.glob("private-subcriteria-*"))
    with pytest.raises(ValueError, match="diagnostic evidence"):
        diagnostics.run(args)


@pytest.mark.parametrize("failure", ["none", "http", "incomplete"])
def test_real_pinned_diagnostic_judge_subprocess_is_separate_and_private(diagnostics, contract, tmp_path, failure):
    python = os.environ.get("BCAL_OFFLINE_JUDGE_PYTHON", sys.executable)
    if subprocess.run([python, "-c", "import autoevals,bc_eval,openai,httpx2"], capture_output=True, check=False).returncode:
        pytest.skip("Pinned offline judge required")
    job, official, specification = contract
    for name, value in (("input", job), ("official", official), ("subcriteria", specification)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    original = (tmp_path / "official.json").read_bytes()
    launcher = """
import json,os,runpy,socket,sys
from pathlib import Path
import httpx2 as httpx
import openai
def forbidden(*args,**kwargs): raise AssertionError("Network forbidden")
socket.socket.connect=socket.socket.connect_ex=socket.getaddrinfo=forbidden
calls=[]
def respond(request):
    calls.append(request)
    assert len(calls)==1
    body=json.loads(request.content)
    assert body["model"]=="gpt-56-ceres" and body["max_completion_tokens"]==4096
    assert "reasoning_effort" not in body
    assert "PRIVATE compound requirement" not in body["messages"][-1]["content"]
    if os.environ["TEST_FAILURE"]=="http":
        return httpx.Response(503,json={"error":{"message":"PRIVATE"}})
    assertions=[] if os.environ["TEST_FAILURE"]=="incomplete" else [
        {"text":"PRIVATE insert requirement","pass":True,"reasoning":"PRIVATE"},
        {"text":"PRIVATE modify requirement","pass":False,"reasoning":"PRIVATE"}]
    return httpx.Response(200,json={"id":"offline","object":"chat.completion","created":0,"model":"gpt-56-ceres","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":json.dumps({"assertions":assertions})}}]})
real=openai.OpenAI
openai.OpenAI=lambda **kwargs:real(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(respond)))
sys.path.insert(0,str(Path(sys.argv[1]).parent))
sys.argv=sys.argv[1:]
try: runpy.run_path(sys.argv[0],run_name="__main__")
finally: Path(os.environ["TEST_CALL_COUNT"]).write_text(str(len(calls)))
"""
    result = subprocess.run(
        [
            python,
            "-c",
            launcher,
            str(ROOT / "scripts" / "bcal_judge_subcriteria.py"),
            "--input",
            str(tmp_path / "input.json"),
            "--official-output",
            str(tmp_path / "official.json"),
            "--subcriteria",
            str(tmp_path / "subcriteria.json"),
            "--output",
            str(tmp_path / "diagnostic.json"),
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
        env={**os.environ, "TEST_FAILURE": failure, "TEST_CALL_COUNT": str(tmp_path / "calls"), "BCAL_STUDY_CHAT_URL": "https://offline.invalid", "BCAL_SDK_PROXY_KEY": "PRIVATE"},
    )
    assert result.returncode == (0 if failure == "none" else 1), result.stderr
    assert (tmp_path / "calls").read_text() == "1"
    safe = json.loads((tmp_path / "diagnostic.json").read_bytes())
    assert safe["status"] == ("completed" if failure == "none" else "failed")
    assert [item["verdict"] for item in safe["criteria"]] == (["pass", "fail"] if failure == "none" else ["unavailable", "unavailable"])
    assert "PRIVATE" not in json.dumps(safe) + result.stdout + result.stderr
    assert (tmp_path / "official.json").read_bytes() == original
