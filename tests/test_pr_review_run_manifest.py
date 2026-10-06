import json
from copy import deepcopy
from pathlib import Path

import pytest

from bcbench.agent.pr_review.run_manifest import FindingIdNormalization, LocationRangeNormalization, RunManifest, load_run_manifest, validate_review_reports, validate_run_manifest
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


def privacy_normalization() -> dict:
    # PR80 @ 4a0885e207cf96617b33d54d0146debbcf7d9841 replays run 37310924454/privacy-015.
    # Handoff SHA256: c313a4ad40d270f4f77821ac36e375baaf107b8944fb8673e1d27d42c1e8b054.
    findings = [
        ("ai-context", "AIContextBuilder.Codeunit.al", 25, 23),
        ("customer-export", "CustomerDataExporter.Codeunit.al", 24, 20),
        ("crm-sync", "ExternalCRMSync.Codeunit.al", 23, 19),
        ("email", "OutboxEmailDispatcher.Codeunit.al", 23, 18),
    ]
    return {
        "raw_report_path": "leaf-results/03-al-privacy-review/_review-report.raw.json",
        "raw_report_sha256": "26aead0958e6ffe60c947f740b95ecf016783116a88d1254e87cea5c54c10107",
        "changes": [
            *[
                {
                    "kind": "finding-id",
                    "finding_index": index,
                    "original_id": f"privacy-notice-consent-for-external-data-transfer-{suffix}",
                    "canonical_id": "microsoft/knowledge/privacy/privacy-notice-consent-for-external-data-transfer.md",
                }
                for index, (suffix, _, _, _) in enumerate(findings)
            ],
            *[
                {
                    "kind": "location-range",
                    "finding_index": index,
                    "file": f"src/{file}",
                    "line": line,
                    "original_range": {"start-line": start, "end-line": line},
                }
                for index, (_, file, line, start) in enumerate(findings)
            ],
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


def test_legacy_manifest_roundtrip_preserves_omission_and_other_nulls(tmp_path):
    payload = valid_manifest()
    manifest = _load(tmp_path, payload)

    assert all(process.normalization is None for process in manifest.processes)
    assert manifest.model_dump() == payload
    assert json.loads(manifest.model_dump_json()) == payload
    assert RunManifest.model_validate_json(manifest.model_dump_json()) == manifest


@pytest.mark.parametrize("kind", ["finding-id", "location-range", "combined"])
def test_normalization_roundtrip_retains_exact_audit_fields(tmp_path, kind):
    payload = valid_manifest()
    normalization = privacy_normalization()
    if kind != "combined":
        normalization["changes"] = [change for change in normalization["changes"] if change["kind"] == kind]
    payload["processes"][0]["normalization"] = normalization
    manifest = _load(tmp_path, payload)
    _validate(manifest)
    _write_reports(tmp_path, payload)
    validate_review_reports(manifest, tmp_path)

    assert manifest.model_dump() == payload
    assert json.loads(manifest.model_dump_json()) == payload
    assert RunManifest.model_validate_json(manifest.model_dump_json()) == manifest
    audit = manifest.processes[0].normalization
    assert audit is not None
    assert audit.raw_report_path == normalization["raw_report_path"]
    assert audit.raw_report_sha256 == normalization["raw_report_sha256"]
    ids = [change for change in audit.changes if isinstance(change, FindingIdNormalization)]
    ranges = [change for change in audit.changes if isinstance(change, LocationRangeNormalization)]
    assert len(ids) == (0 if kind == "location-range" else 4)
    assert len(ranges) == (0 if kind == "finding-id" else 4)
    assert [change.finding_index for change in ids or ranges] == [0, 1, 2, 3]
    assert [(change.line, change.original_range.start_line, change.original_range.end_line) for change in ranges] == (
        [] if kind == "finding-id" else [(25, 23, 25), (24, 20, 24), (23, 19, 23), (23, 18, 23)]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param(lambda n: n.update(extra=True), id="audit-extra"),
        pytest.param(lambda n: n.pop("raw_report_path"), id="missing-raw-path"),
        pytest.param(lambda n: n.pop("raw_report_sha256"), id="missing-raw-hash"),
        pytest.param(lambda n: n.pop("changes"), id="missing-changes"),
        pytest.param(lambda n: n.update(changes=[]), id="empty-changes"),
        pytest.param(lambda n: n.update(changes={}), id="nonarray-changes"),
        pytest.param(lambda n: n["changes"][0].update(extra=True), id="id-extra"),
        pytest.param(lambda n: n["changes"][0].pop("original_id"), id="missing-original-id"),
        pytest.param(lambda n: n["changes"][0].pop("canonical_id"), id="missing-canonical-id"),
        pytest.param(lambda n: n["changes"][0].pop("finding_index"), id="missing-index"),
        pytest.param(lambda n: n["changes"][0].pop("kind"), id="missing-kind"),
        pytest.param(lambda n: n["changes"][0].update(kind="unknown"), id="unknown-kind"),
        pytest.param(lambda n: n["changes"][0].update(kind="location-range"), id="wrong-union-shape"),
        pytest.param(lambda n: n["changes"][0].update(original_id=n["changes"][0]["canonical_id"]), id="unchanged-id"),
        pytest.param(lambda n: n["changes"][4].update(extra=True), id="range-extra"),
        pytest.param(lambda n: n["changes"][4].update(finding_id="invented"), id="range-has-no-finding-id"),
        pytest.param(lambda n: n["changes"][4].pop("file"), id="missing-file"),
        pytest.param(lambda n: n["changes"][4].pop("line"), id="missing-line"),
        pytest.param(lambda n: n["changes"][4].pop("original_range"), id="missing-range"),
        pytest.param(lambda n: n["changes"][4]["original_range"].update(extra=True), id="endpoint-extra"),
        pytest.param(lambda n: n["changes"][4]["original_range"].pop("start-line"), id="missing-start"),
        pytest.param(lambda n: n["changes"][4]["original_range"].pop("end-line"), id="missing-end"),
        pytest.param(lambda n: n["changes"][4]["original_range"].update(start_line=23), id="unaliased-start"),
        pytest.param(lambda n: n["changes"][4]["original_range"].update({"start-line": 25}), id="unchanged-range"),
        pytest.param(lambda n: n["changes"][4]["original_range"].update({"start-line": 26, "end-line": 27}), id="anchor-before-range"),
        pytest.param(lambda n: n["changes"][4]["original_range"].update({"end-line": 24}), id="anchor-after-range"),
        pytest.param(lambda n: n["changes"][4]["original_range"].update({"end-line": 22}), id="reversed-range"),
        pytest.param(lambda n: n["changes"].append(deepcopy(n["changes"][0])), id="duplicate-id-index"),
        pytest.param(lambda n: n["changes"].append(deepcopy(n["changes"][4])), id="duplicate-range-index"),
    ],
)
def test_rejects_malformed_normalization(tmp_path, mutation):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = normalization = privacy_normalization()
    mutation(normalization)

    with pytest.raises(AgentError, match="normalization"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n", None, 123, True])
def test_rejects_malformed_raw_hash(tmp_path, value):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = normalization = privacy_normalization()
    normalization["raw_report_sha256"] = value
    with pytest.raises(AgentError, match="raw_report_sha256"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("field", ["raw_report_path", "file", "original_id", "canonical_id"])
@pytest.mark.parametrize("value", ["", None, 123, True])
def test_rejects_invalid_normalization_strings(tmp_path, field, value):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = normalization = privacy_normalization()
    target = normalization if field == "raw_report_path" else normalization["changes"][4 if field == "file" else 0]
    target[field] = value
    with pytest.raises(AgentError, match=field):
        _load(tmp_path, payload)


@pytest.mark.parametrize("field", ["raw_report_path", "file"])
def test_rejects_backslash_normalization_paths(tmp_path, field):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = normalization = privacy_normalization()
    target = normalization if field == "raw_report_path" else normalization["changes"][4]
    target[field] = target[field].replace("/", "\\")
    with pytest.raises(AgentError, match=field):
        _load(tmp_path, payload)


@pytest.mark.parametrize("change_index", [0, 4])
@pytest.mark.parametrize("value", [-1, 0.5, "0", True, None])
def test_rejects_invalid_finding_indices(tmp_path, change_index, value):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = normalization = privacy_normalization()
    normalization["changes"][change_index]["finding_index"] = value
    with pytest.raises(AgentError, match="finding_index"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("field", ["line", "start-line", "end-line"])
@pytest.mark.parametrize("value", [0, -1, 1.5, "23", True, None])
def test_rejects_invalid_normalization_lines(tmp_path, field, value):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = normalization = privacy_normalization()
    change = normalization["changes"][4]
    target = change if field == "line" else change["original_range"]
    target[field] = value
    with pytest.raises(AgentError, match=field):
        _load(tmp_path, payload)


@pytest.mark.parametrize(("role", "status"), [("root", "completed"), ("leaf", "failed"), ("root", "failed")])
def test_normalization_requires_completed_leaf(tmp_path, role, status):
    payload = valid_manifest()
    payload["processes"][0].update(role=role, status=status, normalization=privacy_normalization())
    with pytest.raises(AgentError, match="normalization requires a completed leaf"):
        _load(tmp_path, payload)


def test_normalization_rejects_explicit_null(tmp_path):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = None
    with pytest.raises(AgentError, match="normalization must be omitted rather than null"):
        _load(tmp_path, payload)


def test_process_unknown_fields_are_still_forbidden(tmp_path):
    payload = valid_manifest()
    payload["processes"][0].update(normalization=privacy_normalization(), unknown=True)
    with pytest.raises(AgentError, match="unknown"):
        _load(tmp_path, payload)


@pytest.mark.parametrize("status", ["running", "partial", "failed"])
def test_completed_leaf_audit_survives_noncompleted_run_but_does_not_enable_scoring(tmp_path, status):
    payload = valid_manifest()
    payload["processes"][0]["normalization"] = privacy_normalization()
    payload["status"] = status
    if status == "running":
        payload["completed_at"] = None
    elif status == "failed":
        payload["failure_reason"] = "Later process failed"
    manifest = _load(tmp_path, payload)
    assert manifest.model_dump() == payload
    with pytest.raises(AgentError, match=f"status='{status}'"):
        _validate(manifest)


def test_does_not_invent_contiguous_indices_change_order_or_article_id_patterns(tmp_path):
    payload = valid_manifest()
    normalization = privacy_normalization()
    normalization["changes"] = [normalization["changes"][4], normalization["changes"][0]]
    for change in normalization["changes"]:
        change["finding_index"] = 7
    normalization["changes"][1].update(original_id="Legacy ID", canonical_id="Case-Sensitive/Primary.md")
    normalization["changes"][0].update(file="src/Folder with spaces/Example.al", line=24)
    payload["processes"][0]["normalization"] = normalization
    assert _load(tmp_path, payload).model_dump() == payload
