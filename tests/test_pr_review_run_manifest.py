import json
from copy import deepcopy
from pathlib import Path

import pytest

from bcbench.agent.pr_review.run_manifest import load_run_manifest, validate_review_reports, validate_run_manifest
from bcbench.exceptions import AgentError

ENGINE_COMMIT = "e" * 40
BCQUALITY_COMMIT = "b" * 40
CLI_VERSION = "1.0.83"


def _metrics(model: str) -> dict:
    return {
        "cli_version": CLI_VERSION,
        "models": [model],
        "usage_complete": True,
        "malformed_records": 0,
        "total_tokens": 10,
    }


def _process(role: str, ordinal: int, skill_id: str, model: str) -> dict:
    return {
        "role": role,
        "ordinal": ordinal,
        "skill_id": skill_id,
        "requested_model": model,
        "observed_models": [model],
        "status": "completed",
        "started_at": "2026-09-14T12:00:00.0000000Z",
        "completed_at": "2026-09-14T12:00:01.0000000Z",
        "duration_seconds": 1.0,
        "exit_code": 0,
        "report_path": f"{role}-results/{ordinal}/_review-report.json",
        "failure_reason": None,
        "metrics": _metrics(model),
    }


def valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "status": "completed",
        "started_at": "2026-09-14T12:00:00.0000000Z",
        "completed_at": "2026-09-14T12:00:03.0000000Z",
        "failure_reason": None,
        "engine": {
            "repository": "microsoft/BC-ALAgents",
            "commit": ENGINE_COMMIT,
            "agent_version": "1.6.6",
        },
        "bcquality": {
            "commit": BCQUALITY_COMMIT,
            "source_snapshot": "a" * 64,
        },
        "configuration": {
            "copilot_cli_version": CLI_VERSION,
            "root_model": "claude-sonnet-5",
            "leaf_model": "gpt-5.4",
            "leaf_execution": "serial",
            "max_leaf_concurrency": 4,
            "cli_timeout_minutes": 30,
            "minimum_severity": "Medium",
            "agent_minimum_severity": "Medium",
            "review_source": "local",
        },
        "plan": {
            "skill_id": "al-code-review",
            "leaf_count": 2,
            "leaf_ids": ["al-performance-review", "al-security-review"],
        },
        "processes": [
            _process("leaf", 1, "al-performance-review", "gpt-5.4"),
            _process("leaf", 2, "al-security-review", "gpt-5.4"),
            _process("root", 3, "al-code-review", "claude-sonnet-5"),
        ],
    }


def _load(tmp_path: Path, payload: dict):
    path = tmp_path / "_run-manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_run_manifest(path)


def _validate(manifest) -> None:
    validate_run_manifest(
        manifest,
        engine_commit=ENGINE_COMMIT,
        cli_version=CLI_VERSION,
        root_model="claude-sonnet-5",
        leaf_model="gpt-5.4",
        leaf_execution="serial",
        max_leaf_concurrency=4,
        cli_timeout_minutes=30,
        minimum_severity="Medium",
        agent_minimum_severity="Medium",
    )


def test_accepts_exact_pinned_runtime(tmp_path: Path) -> None:
    _validate(_load(tmp_path, valid_manifest()))


def test_accepts_bcquality_revision_resolved_by_pinned_engine(tmp_path: Path) -> None:
    payload = valid_manifest()
    payload["bcquality"]["commit"] = "f" * 40

    _validate(_load(tmp_path, payload))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(status="partial"), "status='partial'"),
        (lambda data: data["engine"].update(commit="f" * 40), "engine.commit"),
        (lambda data: data["bcquality"].update(commit=None), "bcquality.commit is missing"),
        (lambda data: data["configuration"].update(leaf_model="gpt-5.6-luna"), "leaf_model"),
        (lambda data: data["processes"][0].update(observed_models=["gemini-3.6-flash"]), "model telemetry"),
        (lambda data: data["processes"][0]["metrics"].update(usage_complete=False), "process metrics"),
        (lambda data: data["configuration"].update(cli_timeout_minutes=45), "cli_timeout_minutes"),
        (lambda data: data["configuration"].update(minimum_severity="High"), "minimum_severity"),
        (lambda data: data["configuration"].update(agent_minimum_severity="High"), "agent_minimum_severity"),
        (lambda data: data["processes"].reverse(), "process ordinals"),
    ],
)
def test_rejects_contaminated_or_incomplete_runtime(tmp_path: Path, mutation, message: str) -> None:
    payload = deepcopy(valid_manifest())
    mutation(payload)

    with pytest.raises(AgentError, match=message):
        _validate(_load(tmp_path, payload))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(completed_at=None), "completed manifest requires completed_at"),
        (lambda data: data.update(failure_reason="unexpected"), "completed manifest must not have failure_reason"),
        (lambda data: data.update(status="failed"), "failed manifest requires failure_reason"),
        (lambda data: data.update(status="failed", failure_reason="leaf failed", completed_at=None), "failed manifest requires completed_at"),
        (lambda data: data.update(status="running"), "running manifest must not have completed_at"),
    ],
)
def test_rejects_inconsistent_manifest_lifecycle(tmp_path: Path, mutation, message: str) -> None:
    payload = valid_manifest()
    mutation(payload)

    with pytest.raises(AgentError, match=message):
        _load(tmp_path, payload)


def test_rejects_missing_process_cli_version(tmp_path: Path) -> None:
    payload = valid_manifest()
    payload["processes"][0]["metrics"]["cli_version"] = None

    with pytest.raises(AgentError, match="process metrics"):
        _validate(_load(tmp_path, payload))


@pytest.mark.parametrize(("observed", "valid"), [(None, True), ("1.0.88", True), ("1.0.83", False), ("", False)])
def test_cli_1088_allows_only_documented_missing_otel_version(tmp_path: Path, observed, valid):
    payload = valid_manifest()
    payload["configuration"]["copilot_cli_version"] = "1.0.88"
    for process in payload["processes"]:
        process["metrics"]["cli_version"] = observed
    manifest = _load(tmp_path, payload)
    kwargs = {
        "engine_commit": ENGINE_COMMIT,
        "cli_version": "1.0.88",
        "root_model": "claude-sonnet-5",
        "leaf_model": "gpt-5.4",
        "leaf_execution": "serial",
        "max_leaf_concurrency": 4,
        "cli_timeout_minutes": 30,
        "minimum_severity": "Medium",
        "agent_minimum_severity": "Medium",
    }
    if valid:
        validate_run_manifest(manifest, **kwargs)
        assert manifest.processes[0].metrics.cli_version == observed
    else:
        with pytest.raises(AgentError, match="process metrics"):
            validate_run_manifest(manifest, **kwargs)


def _write_reports(tmp_path, payload):
    schema_path = tmp_path / "bcquality" / "schemas" / "findings-report.schema.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text(json.dumps({"type": "object", "required": ["skill", "outcome", "findings"]}), encoding="utf-8")
    leaves = [{"skill": {"id": leaf_id}, "outcome": "completed", "findings": []} for leaf_id in payload["plan"]["leaf_ids"]]
    reports = [*leaves, {"skill": {"id": "al-code-review"}, "outcome": "completed", "findings": [], "sub-results": deepcopy(leaves)}]
    for process, report in zip(payload["processes"], reports, strict=True):
        path = tmp_path / process["report_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report), encoding="utf-8")
    return reports


@pytest.mark.parametrize("outcome", ["completed", "not-applicable", "no-knowledge"])
def test_accepts_consistent_original_reports(tmp_path, outcome):
    payload = valid_manifest()
    reports = _write_reports(tmp_path, payload)
    reports[0]["outcome"] = outcome
    reports[-1]["sub-results"][0]["outcome"] = outcome
    for process, report in zip(payload["processes"], reports, strict=True):
        (tmp_path / process["report_path"]).write_text(json.dumps(report), encoding="utf-8")
    validate_review_reports(_load(tmp_path, payload), tmp_path)


@pytest.mark.parametrize(
    ("report_index", "mutation", "message"),
    [
        (0, lambda report: report.update(outcome="failed"), "unusable outcome"),
        (0, lambda report: report.update(outcome="partial"), "unusable outcome"),
        (0, lambda report: report.update(**{"sub-results": []}), "root-only"),
        (0, lambda report: report["skill"].update(id="other"), "wrong skill"),
        (0, lambda report: report.pop("findings"), "pinned BCQuality schema"),
        (0, lambda report: report.update(outcome="no-knowledge", findings=[{}]), "inactive leaf"),
        (2, lambda report: report.update(outcome="partial"), "unusable outcome"),
        (2, lambda report: report["sub-results"].pop(), "ordered leaf plan"),
        (2, lambda report: report["sub-results"].reverse(), "ordered leaf plan"),
        (2, lambda report: report["sub-results"][0].update(outcome="failed"), "disagrees"),
        (2, lambda report: report["sub-results"][0].update(**{"sub-results": [{"outcome": "failed"}]}), "nested delegation"),
        (2, lambda report: report.update(**{"skipped-sub-skills": ["al-security-review"]}), "skips planned"),
    ],
)
def test_completed_manifest_does_not_hide_original_report_failure(tmp_path, report_index, mutation, message):
    payload = valid_manifest()
    reports = _write_reports(tmp_path, payload)
    mutation(reports[report_index])
    (tmp_path / payload["processes"][report_index]["report_path"]).write_text(json.dumps(reports[report_index]), encoding="utf-8")
    with pytest.raises(AgentError, match=message):
        validate_review_reports(_load(tmp_path, payload), tmp_path)


@pytest.mark.parametrize("path", [None, "../outside.json", "missing.json"])
def test_original_reports_are_required_inside_output_directory(tmp_path, path):
    payload = valid_manifest()
    _write_reports(tmp_path, payload)
    payload["processes"][0]["report_path"] = path
    with pytest.raises(AgentError):
        validate_review_reports(_load(tmp_path, payload), tmp_path)
