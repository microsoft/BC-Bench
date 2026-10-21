import json

import pytest

from bcbench.evaluate import review_voting as voting
from bcbench.evaluate import review_voting_gate as gate
from tests.test_review_voting import resolved


def make_smoke(root, counts=(1, 0)):
    for entry_id, count in zip(voting.SMOKE, counts, strict=True):
        folder = root / entry_id
        manifest = {
            "status": "completed",
            "engine": {"commit": voting.ENGINE},
            "bcquality": {"commit": voting.KNOWLEDGE},
            "configuration": {
                "root_model": voting.ROOT_MODEL,
                "leaf_model": voting.LEAF_MODEL,
                "copilot_cli_version": voting.CLI,
                "leaf_execution": "serial",
                "max_leaf_concurrency": 4,
                "minimum_severity": "Medium",
                "agent_minimum_severity": "Medium",
            },
            "plan": {"leaf_count": 1, "leaf_ids": ["test-leaf"]},
            "processes": [
                {"role": role, "skill_id": "test-leaf", "requested_model": model, "observed_models": [model], "status": "completed"}
                for role, model in (("leaf", voting.LEAF_MODEL), ("root", voting.ROOT_MODEL))
            ],
        }
        voting.save(folder / "baseline/_run-manifest.json", manifest)
        ids = ["F001"] if count else []
        voting.save(folder / "candidates.json", [{"id": key} for key in ids])
        voting.save(
            folder / "result.json",
            {
                "instance_id": entry_id,
                "config": voting.config(),
                "baseline_complete": True,
                "baseline_scored": True,
                "paired": True,
                "operational_success": True,
                "errors": [],
                "candidates": count,
                "arms": dict.fromkeys("ABC", ids),
                "scores": {arm: {} for arm in "ABC"},
            },
        )
        voting.save(folder / "judge/edges.json", [{"match": True}] if count else [])
        if count:
            voting.save(folder / "judge/metrics.json", {"observed_models": [voting.JUDGE]})
            for n in (1, 2, 3):
                voting.save(folder / f"voter-{n}/decisions.json", [resolved().model_dump(mode="json")])
                voting.save(folder / f"voter-{n}/metrics.json", {"observed_models": [voting.ROOT_MODEL]})


def test_empty_clean_valid_with_one_fully_exercised_case(tmp_path):
    make_smoke(tmp_path)
    assert len(gate.assess_entries(tmp_path)) == 2


def test_no_nonempty_case_is_blocked(tmp_path):
    make_smoke(tmp_path, (0, 0))
    with pytest.raises(ValueError, match="At least one"):
        gate.assess_entries(tmp_path)


@pytest.mark.parametrize("field", ["baseline_complete", "baseline_scored", "paired", "operational_success"])
def test_real_pipeline_failures_remain_blocked(tmp_path, field):
    make_smoke(tmp_path)
    path = tmp_path / voting.SMOKE[0] / "result.json"
    voting.save(path, voting.read(path) | {field: False})
    with pytest.raises(ValueError, match="failure"):
        gate.assess_entries(tmp_path)


def test_invalid_evidence_is_blocked(tmp_path):
    make_smoke(tmp_path)
    voting.save(tmp_path / voting.SMOKE[0] / "voter-2/decisions.json", [resolved(validity="unresolved").model_dump(mode="json")])
    with pytest.raises(ValueError, match="citations exclude"):
        gate.assess_entries(tmp_path)


@pytest.mark.parametrize("stage", ["voter-1", "judge"])
def test_actual_model_mismatch_is_blocked(tmp_path, stage):
    make_smoke(tmp_path)
    voting.save(tmp_path / voting.SMOKE[0] / stage / "metrics.json", {"observed_models": ["wrong-model"]})
    with pytest.raises(ValueError, match="model differs"):
        gate.assess_entries(tmp_path)


def test_baseline_cli_mismatch_is_blocked(tmp_path):
    make_smoke(tmp_path)
    path = tmp_path / voting.SMOKE[0] / "baseline/_run-manifest.json"
    manifest = voting.read(path)
    manifest["configuration"]["copilot_cli_version"] = "wrong"
    voting.save(path, manifest)
    with pytest.raises(ValueError, match="configuration differs"):
        gate.assess_entries(tmp_path)


def test_missing_voter_is_not_silently_skipped(tmp_path):
    make_smoke(tmp_path)
    (tmp_path / voting.SMOKE[0] / "voter-3/decisions.json").unlink()
    with pytest.raises(FileNotFoundError):
        gate.assess_entries(tmp_path)


@pytest.mark.parametrize("changed", ["src/bcbench/agent/pr_review/agent.py", "dataset/codereview.jsonl"])
def test_substantive_runtime_change_rejects_smoke_reuse(monkeypatch, changed):
    monkeypatch.setattr(voting, "checked_command", lambda args: gate.SMOKE_REVISION if "rev-parse" in args else changed)
    with pytest.raises(ValueError, match="beyond"):
        gate.check_revision("new")


def test_non_gate_edit_in_orchestrator_is_rejected(monkeypatch):
    def git(args):
        if "rev-parse" in args:
            return gate.SMOKE_REVISION
        if "diff" in args:
            return "src/bcbench/evaluate/review_voting.py"
        return "changed verifier prompt" if args[-1].startswith("new:") else "original"

    monkeypatch.setattr(voting, "checked_command", git)
    with pytest.raises(ValueError, match="implementation changed"):
        gate.check_revision("new")


def test_assessment_does_not_change_original_files(tmp_path):
    make_smoke(tmp_path)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    gate.assess_entries(tmp_path)
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*.json")}
    assert json.loads(before[tmp_path / voting.SMOKE[1] / "result.json"])["candidates"] == 0
