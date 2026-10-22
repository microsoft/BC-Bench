import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
PWSH = shutil.which("pwsh")
SECRET = "private-command-argument-not-for-artifacts"


@pytest.fixture
def evidence(tmp_path):
    source = tmp_path / "results with spaces" / "123"
    source.mkdir(parents=True)
    usage = {
        "schema_version": 1,
        "metrics_source": "copilot-cli-otel",
        "cli_version": "1.0.88",
        "wall_time_seconds": 10.5,
        **dict.fromkeys(
            (
                "prompt_tokens",
                "cached_tokens",
                "cache_creation_tokens",
                "completion_tokens",
                "reasoning_tokens",
                "total_tokens",
                "api_calls",
                "failed_api_calls",
                "usage_api_calls",
                "malformed_records",
            ),
            0,
        ),
        "ai_credits": 1.2,
        "premium_requests": None,
        "models": ["gpt-5.6-sol", "gpt-5.6-luna"],
        "usage_complete": True,
        "environment": SECRET,
    }
    manifest = {
        "schema_version": 1,
        "status": "completed",
        "started_at": "2026-10-22T00:00:00Z",
        "completed_at": "2026-10-22T00:01:00Z",
        "failure_reason": SECRET,
        "engine": {"repository": "microsoft/BC-ALAgents", "commit": "a" * 40, "agent_version": "1.9", "token": SECRET},
        "bcquality": {"commit": "b" * 40, "source_snapshot": "c" * 64},
        "configuration": {
            "copilot_cli_version": "1.0.88",
            "root_model": "gpt-5.6-sol",
            "leaf_model": "gpt-5.6-luna",
            "leaf_execution": "serial",
            "max_leaf_concurrency": 1,
            "cli_timeout_minutes": 30,
            "minimum_severity": "Medium",
            "agent_minimum_severity": "Medium",
            "review_source": "local",
            "environment": SECRET,
        },
        "plan": {"skill_id": "al-code-review", "leaf_count": 1, "leaf_ids": ["al-security-review"], "prompt": SECRET},
        "processes": [
            {
                "role": "leaf",
                "ordinal": 1,
                "skill_id": "al-security-review",
                "requested_model": "gpt-5.6-luna",
                "observed_models": ["gpt-5.6-luna"],
                "status": "completed",
                "started_at": "2026-10-22T00:00:00Z",
                "completed_at": "2026-10-22T00:01:00Z",
                "duration_seconds": 60,
                "exit_code": 0,
                "failure_reason": SECRET,
                "report_path": SECRET,
                "normalization": {"changes": SECRET},
                "metrics": usage,
            }
        ],
        "prompt": SECRET,
    }
    for name, payload in (("_run-manifest.json", manifest), ("_run-metrics.json", usage)):
        (source / name).write_text(json.dumps(payload), encoding="utf-8-sig")
    (source / "agent-output.txt").write_text(SECRET)
    return source


def run_collection(source, outcome="success"):
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "pr-review-evaluation.yml").read_text())
    steps = workflow["jobs"]["evaluate-with-pr-review"]["steps"]
    collect = next(step for step in steps if step["name"] == "Preserve bounded runtime evidence")
    assert PWSH is not None
    result = subprocess.run(
        [PWSH, "-NoProfile", "-Command", collect["run"]],
        cwd=ROOT,
        env={
            **os.environ,
            "EVALUATION_RESULTS_DIR": str(source.parent),
            "ENTRY_ID": "synthetic__sample-01",
            "EVALUATION_OUTCOME": outcome,
            "WORKFLOW_SHA": "d" * 40,
            "WORKFLOW_RUN_ID": "123",
            "WORKFLOW_RUN_ATTEMPT": "2",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    target = source.parent / "runtime-evidence" / "synthetic__sample-01"
    status = json.loads((target / "evidence-status.json").read_text())
    return result, target, status


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
def test_workflow_collects_only_safe_fields_without_changing_sources(evidence):
    originals = {path.name: path.read_bytes() for path in evidence.iterdir()}
    result, target, status = run_collection(evidence)
    assert result.returncode == 0, result.stderr
    assert {path.name for path in target.iterdir()} == {"_run-manifest.json", "_run-metrics.json", "evidence-status.json"}
    assert SECRET not in "".join(path.read_text() for path in target.iterdir()) + result.stdout + result.stderr
    assert originals == {path.name: path.read_bytes() for path in evidence.iterdir()}
    manifest = json.loads((target / "_run-manifest.json").read_text())
    assert manifest["configuration"]["leaf_model"] == "gpt-5.6-luna"
    assert manifest["processes"][0]["observed_models"] == ["gpt-5.6-luna"]
    assert manifest["processes"][0]["failure_reason_present"] is True
    assert manifest["bcquality"]["commit"] == "b" * 40
    assert status["workflow_sha"] == "d" * 40
    assert status["workflow_run_attempt"] == "2"
    for name, record in status["files"].items():
        assert record["source_sha256"] == hashlib.sha256(originals[name]).hexdigest()
        assert record["artifact_sha256"] == hashlib.sha256((target / name).read_bytes()).hexdigest()


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
@pytest.mark.parametrize(("outcome", "exit_code"), [("success", 1), ("failure", 0), ("cancelled", 0), ("skipped", 0)])
def test_missing_manifest_is_explicit_without_replacing_original_failure(evidence, outcome, exit_code):
    run_collection(evidence)
    (evidence / "_run-manifest.json").unlink()
    result, target, status = run_collection(evidence, outcome)
    assert result.returncode == exit_code
    assert not (target / "_run-manifest.json").exists()
    assert status["evaluation_outcome"] == outcome
    expected = "not_collected_step_skipped" if outcome == "skipped" else "missing"
    assert status["files"]["_run-manifest.json"]["status"] == expected
    if outcome != "skipped":
        assert (target / "_run-metrics.json").exists()
        assert "::error::" in result.stdout if outcome == "success" else "::warning::" in result.stdout


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
@pytest.mark.parametrize("name", ["_run-manifest.json", "_run-metrics.json"])
@pytest.mark.parametrize("bad", ['{"secret": "' + SECRET, json.dumps({"schema_version": 1, "models": {"token": SECRET}})])
def test_invalid_evidence_is_not_uploaded_or_echoed(evidence, name, bad):
    (evidence / name).write_text(bad)
    result, target, status = run_collection(evidence)
    assert result.returncode == 1
    assert status["files"][name]["status"] == "unreadable_or_invalid"
    assert not (target / name).exists()
    assert SECRET not in result.stdout + result.stderr + (target / "evidence-status.json").read_text()


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
@pytest.mark.parametrize(("state", "exit_code"), [("running", 1), ("failed", 1), ("partial", 0), ("completed", 0)])
def test_nonterminal_or_failed_manifest_cannot_masquerade_as_success(evidence, state, exit_code):
    path = evidence / "_run-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = state
    path.write_text(json.dumps(manifest))
    result, target, status = run_collection(evidence)
    assert result.returncode == exit_code
    assert json.loads((target / path.name).read_text())["status"] == state
    assert status["files"][path.name]["status"] == "preserved"


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
def test_early_failure_has_only_an_explicit_missing_evidence_record(evidence):
    (evidence / "_run-manifest.json").unlink()
    (evidence / "_run-metrics.json").unlink()
    result, target, status = run_collection(evidence, "failure")
    assert result.returncode == 0
    assert {path.name for path in target.iterdir()} == {"evidence-status.json"}
    assert all(record["status"] == "missing" for record in status["files"].values())
    assert len(status["problems"]) == 2


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
def test_failed_review_preserves_failed_leaf_status_without_raw_failure_text(evidence):
    path = evidence / "_run-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    manifest["status"] = "failed"
    manifest["processes"][0].update(status="failed", exit_code=None, observed_models=[], metrics=None)
    path.write_text(json.dumps(manifest))
    result, target, status = run_collection(evidence, "failure")
    assert result.returncode == 0
    preserved = json.loads((target / path.name).read_text())
    assert preserved["status"] == "failed"
    assert preserved["processes"][0]["status"] == "failed"
    assert preserved["processes"][0]["exit_code"] is None
    assert status["evaluation_outcome"] == "failure"
    assert SECRET not in (target / path.name).read_text()


@pytest.mark.skipif(PWSH is None, reason="PowerShell is required for the workflow collector")
@pytest.mark.parametrize("bad_models", [{"token": SECRET}, [SECRET, {"token": SECRET}]])
def test_nested_non_scalar_usage_is_rejected_not_copied(evidence, bad_models):
    path = evidence / "_run-metrics.json"
    usage = json.loads(path.read_text(encoding="utf-8-sig"))
    usage["models"] = bad_models
    path.write_text(json.dumps(usage))
    result, target, status = run_collection(evidence)
    assert result.returncode == 1
    assert not (target / path.name).exists()
    assert status["files"][path.name]["status"] == "unreadable_or_invalid"
    assert SECRET not in result.stdout + result.stderr


def test_workflow_preserves_per_entry_evidence_after_failures_without_broad_uploads():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "pr-review-evaluation.yml").read_text())
    steps = workflow["jobs"]["evaluate-with-pr-review"]["steps"]
    review = next(step for step in steps if step.get("id") == "evaluate-review")
    collect = next(step for step in steps if step["name"] == "Preserve bounded runtime evidence")
    upload = next(step for step in steps if step["name"] == "Upload runtime evidence")
    assert '--run-id "${{ github.run_id }}"' in review["run"]
    assert "Join-Path $env:EVALUATION_RESULTS_DIR $env:WORKFLOW_RUN_ID" in collect["run"]
    assert collect["env"]["WORKFLOW_RUN_ID"] == "${{ github.run_id }}"
    assert collect["env"]["EVALUATION_OUTCOME"] == "${{ steps.evaluate-review.outcome }}"
    assert collect["if"] == upload["if"] == "always() && inputs.review-integration != 'none'"
    assert not review.get("continue-on-error")
    assert not collect.get("continue-on-error")
    assert upload["with"]["name"] == "runtime-evidence-${{ github.run_id }}-${{ matrix.entry }}"
    assert set(upload["with"]["path"].splitlines()) == {
        "${{ env.EVALUATION_RESULTS_DIR }}/runtime-evidence/${{ matrix.entry }}/" + name for name in ("evidence-status.json", "_run-manifest.json", "_run-metrics.json")
    }
    assert upload["with"]["if-no-files-found"] == "error"
    assert "--verbose" not in review["run"]
    summary = yaml.safe_load((ROOT / ".github" / "workflows" / "summarize-results.yml").read_text())
    download = next(step for step in summary["jobs"]["summarize-results"]["steps"] if "download-artifact@" in step.get("uses", ""))
    assert download["with"]["pattern"] == "${{ (inputs.dataset != '' || inputs.category == 'code-review') && 'evaluation-results-*' || '*' }}"
