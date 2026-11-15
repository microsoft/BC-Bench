import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_double_study", ROOT / "scripts" / "bcal_governed_study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)


@pytest.fixture
def double_manifest(tmp_path, monkeypatch):
    value = json.loads((ROOT / "experiments" / "bcal-full-gold-judge-diagnostics" / "study.json").read_bytes())
    value.pop("comparisonOf")
    value.update(
        studyId=study.REVIEW_DOUBLE_STUDY,
        reviewValidationOf={"runId": 43594914041, "sourceSha": "69831c644e2151eadcd0c2fa20e02e6addf63fc0"},
        repetitions=[1, 2],
        semanticExecutionCount=440,
        diagnosticSubcriteriaCalls=0,
        reviewPackageProof={"file": "not-admitted.json", "sha256": "0" * 64},
    )
    value["package"] = {**value["package"], "sha256": "1" * 64, "sourceCommitSha": "2" * 40}
    study.write_json(tmp_path / "study.json", value)
    monkeypatch.setattr(study, "INPUTS", tmp_path)
    return value


def test_two_disjoint_repetitions_select_same110_and_reverse_runtime_order(double_manifest, monkeypatch):
    monkeypatch.setenv("BCAL_STUDY_REPETITION", "1")
    first = study.pairs()
    monkeypatch.setenv("BCAL_STUDY_REPETITION", "2")
    second = study.pairs()
    assert len(first) == len(second) == 110
    assert sum(len(pair["order"]) for pair in [*first, *second]) == 440
    assert {pair["instanceId"] for pair in first} == {pair["instanceId"] for pair in second}
    assert all(pair["repeat"] == 1 for pair in first)
    assert all(pair["repeat"] == 2 for pair in second)
    assert all(left["order"] == list(reversed(right["order"])) for left, right in zip(first, second, strict=True))
    assert study.study()["judge"]["model"] == "gpt-56-ceres"
    assert study.study()["maxWorkers"] == 32


@pytest.mark.parametrize("mutation", [{"repetitions": [1, 2, 3]}, {"semanticExecutionCount": 660}, {"diagnosticSubcriteriaCalls": 29}, {"caseCount": 109}, {"judge": {"model": "changed"}}])
def test_rejects_workload_expansion_or_scoring_changes(double_manifest, mutation):
    study.write_json(study.INPUTS / "study.json", {**double_manifest, **mutation})
    with pytest.raises(ValueError, match="selectors and scoring"):
        study.study()


@pytest.mark.parametrize("repetition", ["0", "3", "01", "", "true"])
def test_rejects_other_repetition_identity(double_manifest, monkeypatch, repetition):
    monkeypatch.setenv("BCAL_STUDY_REPETITION", repetition)
    with pytest.raises(ValueError, match="two separately identified"):
        study.pairs()


def test_rejects_old_package_and_unavailable_proof(double_manifest):
    with pytest.raises(FileNotFoundError):
        study.verify_review_package_proof()
    double_manifest["package"].update(sha256="17683f88c9ebed8dbe9570479fa8870a2ce41c5396c50521a107a5716b784bef")
    study.write_json(study.INPUTS / "study.json", double_manifest)
    with pytest.raises(ValueError, match="package42492"):
        study.study()


@pytest.mark.parametrize("mutation", ["package", "native", "authority", "provider", "prompt"])
def test_review_proof_rejects_unverified_runtime_or_mismatched_package(tmp_path, monkeypatch, mutation):
    config = {"studyId": study.REVIEW_DOUBLE_STUDY, "package": {"sha256": "1" * 64, "sourceCommitSha": "2" * 40}}
    proof = {
        "status": "passed",
        "packageSha256": config["package"]["sha256"],
        "packageSourceCommitSha": config["package"]["sourceCommitSha"],
        "actualPackagedPromptsVerified": True,
        "legacyAcceptanceReviewVerified": True,
        "nativeSelfReviewVerified": True,
        "toolAuthorityPreserved": True,
        "providerRequests": 0,
        "networkRequests": 0,
        "promptHashes": {"legacyAcceptance": "3" * 64, "nativeSelfReview": "4" * 64},
    }
    if mutation == "package":
        proof["packageSha256"] = "5" * 64
    elif mutation == "native":
        proof["nativeSelfReviewVerified"] = False
    elif mutation == "authority":
        proof["toolAuthorityPreserved"] = False
    elif mutation == "provider":
        proof["providerRequests"] = 1
    else:
        proof["promptHashes"]["nativeSelfReview"] = None
    path = tmp_path / "proof.json"
    study.write_json(path, proof)
    config["reviewPackageProof"] = {"file": "proof.json", "sha256": study.digest(path)}
    monkeypatch.setattr(study, "ROOT", tmp_path)
    monkeypatch.setattr(study, "study", lambda: config)
    monkeypatch.setattr(study, "verify_proof_sources", lambda _: None)
    with pytest.raises(ValueError, match="packaged strengthened review"):
        study.verify_review_package_proof()


def test_double_workflow_serializes_repetitions_and_requires_shared_source_admission():
    caller = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-evaluation.yml").read_text())
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "bcal-governed-policy.yml").read_text())
    assert "'bcal-full-gold-strengthened-review-double1-entry'" in caller["concurrency"]["group"]
    assert "'bcal-full-gold-strengthened-review-double1'" in workflow["concurrency"]["group"]
    assert workflow["env"]["BCAL_STUDY_REPETITION"] == "${{ inputs.phase == 'full-gold-review-2' && '2' || '1' }}"
    gate = next(step["run"] for step in workflow["jobs"]["admit"]["steps"] if step.get("id") == "gold")
    assert "'*paired full-gold-review-preflight'" in gate
    assert "$reviewRuns[0].head_sha -ne $env:GITHUB_SHA" in gate
    assert "$reviewRuns[0].conclusion -ne 'success'" in gate
    assert "$study.diagnosticSubcriteriaCalls -ne 0" in gate
    assert "reviewPackageProof" in gate
    assert not any("bcal_judge_subcriteria.py" in step.get("run", "") for job in workflow["jobs"].values() for step in job["steps"])
