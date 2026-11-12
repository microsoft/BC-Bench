import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("governed_study_test", ROOT / "scripts" / "bcal_governed_study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


def test_fixed_cohort_is_repeat_aware_and_counterbalanced():
    pairs = study.pairs()
    assert len({(pair["tier"], pair["instanceId"]) for pair in pairs}) == 4
    assert len({(pair["instanceId"], pair["repeat"], runtime) for pair in pairs for runtime in pair["order"]}) == 16
    for first, second in zip(pairs[::2], pairs[1::2], strict=True):
        assert first["instanceId"] == second["instanceId"]
        assert first["order"] == second["order"][::-1]


def test_carry_forward_hold_cannot_be_ignored(tmp_path, monkeypatch):
    original = study.INPUTS
    config = study.study()
    config["budget"]["unresolvedLocalReservationSeconds"] = 180000
    (tmp_path / "symbols.json").write_bytes((original / "symbols.json").read_bytes())
    study.write_json(tmp_path / "study.json", config)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    with pytest.raises(ValueError, match="carry-forward"):
        study.study()


def test_route_receipt_rejects_missing_stickiness_and_private_fields(tmp_path):
    path = tmp_path / "route.json"
    value = {"requests": 2, "http200": 2, "ticketsReturned": 0, "ticketsReplayed": 0, "sessionStable": True, "modelStable": True}
    study.write_json(path, value)
    with pytest.raises(ValueError, match="sticky"):
        study.route_receipt(path)
    value.update(ticketsReturned=2, ticketsReplayed=1)
    study.write_json(path, value)
    assert study.route_receipt(path) == value
    value["ticket"] = "must-not-be-published"
    study.write_json(path, value)
    with pytest.raises(ValueError, match="Unexpected"):
        study.route_receipt(path)


def test_package_admission_reuses_exact_installed_action_archive(tmp_path, monkeypatch):
    import hashlib

    installed = tmp_path / "store" / "30.0" / "tools" / "net10.0" / "any" / "bcal.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"binary")
    archive = installed.parents[3] / "test.package.30.0.nupkg"
    archive.write_bytes(b"exact governed archive")
    config = {"id": "test.package", "version": "30.0", "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size, "sourceCommitSha": "a" * 40}
    folder = tmp_path / "private"
    (folder / "stage").mkdir(parents=True)
    monkeypatch.setenv("BCAL_STUDY_INSTALLED_BINARY", str(installed))
    monkeypatch.setattr(study, "study", lambda: {"package": config})
    monkeypatch.setattr(study, "verify_package", lambda _: installed)
    assert study.prepare_package(folder)["sha256"] == config["sha256"]
    assert (folder / "package.nupkg").read_bytes() == archive.read_bytes()
    (folder / "package.nupkg").unlink()
    archive.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="archive bytes differ"):
        study.prepare_package(folder)


def test_sanitized_legacy_failure_never_exports_or_scores_success():
    transcript = {
        "executionIdentity": {"sourceCommitSha": study.study()["package"]["sourceCommitSha"]},
        "runtimeIdentity": {
            "agentRuntime": "legacy",
            "requestedPlanningMode": None,
            "planningMode": "bcal",
            "planningMechanism": "bcal-structured",
            "completionPolicy": "bcal-whole-result-review",
            "systemPromptSha256": "a" * 64,
            "toolCatalogSha256": "b" * 64,
        },
        "completed": False,
        "failure": {"message": "PRIVATE GENERATED CONTENT"},
        "export": {"success": True},
        "totals": {},
        "steps": [],
        "evidence": {"trace": {"truncated": False, "omittedEventCount": 0, "events": []}},
    }
    value = study.sanitize_row({"transcript": transcript, "error_message": "PRIVATE GENERATED CONTENT"}, "legacy")
    assert value["completed"] is False
    assert value["exported"] is False
    assert value["usage"]["promptTokens"] is None
    assert "PRIVATE" not in json.dumps(value)


def test_trace_projection_never_publishes_tool_payload_or_unknown_text():
    raw = {"truncated": False, "omittedEventCount": 0, "events": [{"type": "tool_started", "sequence": 1, "toolName": "PRIVATE", "arguments": {"secret": "PRIVATE"}, "inputHash": "PRIVATE"}]}
    safe = study.trace_projection({"evidence": {"trace": raw}})
    assert len(safe["events"]) == 1
    assert "PRIVATE" not in json.dumps(safe)
    raw["truncated"] = True
    with pytest.raises(ValueError, match="truncated"):
        study.trace_projection({"evidence": {"trace": raw}})


def test_transport_reuses_proxy_without_loading_the_full_bench_environment():
    import subprocess
    import sys

    script = ROOT / "scripts" / "bcal_study_transport.py"
    code = f"import runpy,sys; m=runpy.run_path({str(script)!r}); assert m['load_proxy']()._handler; assert 'bcbench.agent' not in sys.modules"
    subprocess.run([sys.executable, "-I", "-S", "-c", code], check=True)


def test_legacy_model_response_is_not_gated_on_the_native_sdk_counter():
    legacy = {"agentRuntimeEvidence": [{"modelRequests": 0}], "evidence": {"trace": {"events": [{"type": "model_response", "succeeded": True}]}}}
    assert study.model_response_observed({"http200": 8}, legacy) is True
    assert study.model_response_observed({"http200": 0}, legacy) is False
    legacy["evidence"]["trace"]["events"][0]["succeeded"] = False
    assert study.model_response_observed({"http200": 1}, legacy) is True
    assert study.model_response_observed({"http200": 1}, {"agentRuntimeEvidence": [{"modelRequests": 1}]}) is True
    assert study.model_response_observed({"http200": 1}, {"agentRuntimeEvidence": [{"modelRequests": 0}]}) is False


def test_summary_retains_missing_cells_and_refuses_complete_claim(tmp_path):
    from argparse import Namespace

    with pytest.raises(ValueError, match="incomplete"):
        study.summary(Namespace(work=tmp_path, output=tmp_path / "summary"))
    result = json.loads((tmp_path / "summary" / "comparison.json").read_bytes())
    assert result["complete"] is False
    assert result["scoreable"] == 0
    assert len(result["missing"]) == 16


def test_existing_workflow_is_the_only_dispatch_and_reuses_actions():
    caller = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-evaluation.yml").read_text())
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-governed-policy.yml").read_text())
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-bcal-governed-study" / "action.yml").read_text())
    assert caller["jobs"]["get-entries"]["if"] == "inputs.validation-phase == '' || inputs.validation-phase == 'ordinary'"
    assert workflow["jobs"]["pairs"]["strategy"]["max-parallel"] == 4
    assert any(step.get("uses") == "./.github/actions/install-bcal" for step in action["runs"]["steps"])
    assert any(step.get("uses") == "./.github/actions/setup-python-uv" for step in action["runs"]["steps"])
    assert all(
        step.get("with", {}).get("path") in ("study-sanitized\\*.json", "study-summary\\*")
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/upload-artifact@")
    )
