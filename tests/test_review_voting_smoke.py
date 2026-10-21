import json
from types import SimpleNamespace

import pytest

from tools import review_voting_smoke as smoke


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke.pilot.subprocess, "run", lambda *a, **k: pytest.fail("No real process"))
    for name in ("run_pr_review_agent", "score_arms", "copy_tree", "check_snapshot", "preflight", "prepare"):
        monkeypatch.setattr(smoke.pilot, name, lambda *a, **k: pytest.fail("No baseline/judge/copy/preparation"))
    cases = []
    for i, instance, _ in smoke.CASES:
        case = {"case": f"case-{i:02}", "instance_id": instance, "source": "source", "knowledge": "knowledge", "context": {}, "candidates": [{"id": "F001"}], "guards": {}}
        cases.append(case)
        smoke.pilot.save(tmp_path / case["case"] / "context-receipt.json", {})
    manifest = {"guards": {"cases": cases, "selection": {"cli": {"path": "mock"}}}}
    monkeypatch.setattr(smoke, "execution_guards", lambda _: manifest)
    monkeypatch.setattr(smoke.pilot, "shared_root_guards", lambda *a: {})
    return tmp_path


def test_exact_six_sequential_verifiers_no_other_calls(prepared, monkeypatch):
    calls = []

    def invoke(folder, *args):
        calls.append(folder)
        assert not calls[:-1] or (calls[-2] / "smoke-assessment.json").is_file()
        return []

    monkeypatch.setattr(smoke.pilot, "run_verifier", invoke)
    monkeypatch.setattr(smoke, "assess_call", lambda *a: {"gate_passed": True})
    smoke.execute(prepared)
    assert [p.parent.name + "/" + p.name for p in calls] == [f"case-{i:02}/voter-{v}" for i in (3, 6) for v in (1, 2, 3)]
    outcome = smoke.read(prepared / "outcome.json")
    assert outcome["verifier_starts"] == outcome["returned_calls"] == 6
    assert outcome["baseline_calls"] == outcome["judge_calls"] == 0


@pytest.mark.parametrize("failure", ["process", "evidence"])
def test_first_failure_stops_without_retry(prepared, monkeypatch, failure):
    calls = []

    def invoke(folder, *args):
        calls.append(folder)
        if failure == "process":
            raise RuntimeError("permission failure")
        return []

    monkeypatch.setattr(smoke.pilot, "run_verifier", invoke)
    monkeypatch.setattr(smoke, "assess_call", lambda *a: {"gate_passed": False})
    with pytest.raises((ValueError, RuntimeError)):
        smoke.execute(prepared)
    assert len(calls) == 1
    assert smoke.read(prepared / "outcome.json")["status"] == "halted"


def test_prior_phase_start_rejected(tmp_path):
    (tmp_path / "execution").mkdir()
    with pytest.raises(FileExistsError):
        smoke.execution_guards(tmp_path)


def test_prior_voter_rejected(tmp_path):
    (tmp_path / "case-06" / "voter-3").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        smoke.execution_guards(tmp_path)


@pytest.mark.parametrize(("tool", "valid", "passed"), [("view", True, True), ("powershell", True, False), ("view", False, False)])
def test_live_gate_requires_valid_evidence_and_only_read_tools(tmp_path, tool, valid, passed):
    event = {"type": "tool.execution_start", "data": {"toolName": tool}}
    (tmp_path / "stdout.jsonl").write_text(json.dumps(event))
    decision = smoke.ResolvedDecision.model_validate_json(
        json.dumps(
            {
                "decision": {
                    "id": "F001",
                    "verdict": "insufficient_evidence",
                    "trigger": "test",
                    "call_path_and_guards": "test",
                    "impact": "test",
                    "counterevidence": "test",
                    "evidence": [],
                    "source_view_status": "available",
                },
                "evidence_resolution": "tool_view_matched" if valid else "unresolved",
                "reason": "fixture",
                "evidence": [],
            }
        )
    )
    assert smoke.assess_call(tmp_path, [decision])["gate_passed"] == passed


@pytest.mark.parametrize("problem", ["selection", "expected", "candidate", "started"])
def test_historical_mismatch_blocks_before_inference(tmp_path, monkeypatch, problem):
    config = smoke.pilot.load_config()
    if problem == "selection":
        config["cases"][2] = "wrong-case"
    monkeypatch.setattr(smoke.pilot, "load_config", lambda: config)
    monkeypatch.setattr(smoke.pilot, "sha", lambda _: "hash")
    monkeypatch.setattr(smoke.pilot, "shared_root_guards", lambda *a: {})
    monkeypatch.setattr(smoke.pilot, "run_verifier", lambda *a: pytest.fail("No inference"))
    monkeypatch.setattr(smoke.CodeReviewEntry, "model_validate", lambda data: SimpleNamespace(**data))
    monkeypatch.setattr(smoke.ReviewComment, "model_validate", lambda data: SimpleNamespace(model_dump=lambda **k: data))
    smoke.pilot.save(tmp_path / "selection.json", {"config": config})
    smoke.pilot.save(tmp_path / "checkpoint.json", {"artifact_sha256": {}})
    smoke.pilot.save(tmp_path / "inputs.json", {"source_sha256": ["sha"] * 6})
    smoke.pilot.save(tmp_path / "zero-inference-proof.json", {"origin": str(tmp_path)})
    case = tmp_path / "case-03"
    if problem == "started":
        (case / "voter-1").mkdir(parents=True)
    smoke.pilot.save(case / "gold-private.json", {"instance_id": smoke.CASES[0][1], "expected_comments": [] if problem == "expected" else [{}]})
    smoke.pilot.save(case / "candidates.json", [] if problem == "candidate" else [{"id": "F001", "comment": {}}])
    smoke.pilot.save(case / "frozen-review.json", [{}])
    with pytest.raises(ValueError, match=r"mismatch|already started"):
        smoke.historical_guards(tmp_path)
