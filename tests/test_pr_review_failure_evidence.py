import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("failure_evidence", ROOT / "tools" / "collect_pr_review_failure.py")
assert SPEC is not None
assert SPEC.loader is not None
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


@pytest.fixture
def diagnostic():
    return {
        "schema_version": 1,
        "leaf_ordinal": 1,
        "process": {"exit_code": 1, "timeout_observed": False, "signal": "unknown"},
        "capture": {
            "state": "complete",
            "history_omitted": False,
            "records_limited": False,
            "leading_record_discarded": False,
            "incomplete_record_discarded": False,
            "malformed_records": 0,
            "unsupported_records": 0,
        },
        "cli": {
            "cause": "unknown",
            "observations": [
                {"type": "model.call_failure", "status_code": 403, "status_state": "available", "failureKind": "api", "transport": "http", "source": "top_level", "badRequestKind": "unknown"}
            ],
        },
        "engine": {"stage": "telemetry", "code": "telemetry_invalid"},
    }


@pytest.fixture
def inputs(tmp_path: Path, diagnostic):
    source = tmp_path / "source"
    leaf = source / "leaf-results" / "01-al-performance-review"
    leaf.mkdir(parents=True)
    ids = ["al-performance-review", *(f"al-domain-{i:02}-review" for i in range(2, 20))]
    (source / "_run-manifest.json").write_text(json.dumps({"plan": {"leaf_count": 19, "leaf_ids": ids}}), encoding="utf-8")
    (leaf / "_cli-failure-diagnostic.json").write_text(json.dumps(diagnostic), encoding="utf-8")
    return source, leaf, tmp_path / "output"


def test_failure_projection_never_reads_streams_or_retains_unknown_metrics(inputs, monkeypatch: pytest.MonkeyPatch) -> None:
    source, leaf, output = inputs
    secret = "ghp_" + "Z" * 40
    (leaf / "stdout.txt").write_text(f"PROMPT: {secret}\nhttps://private.example/?token={secret}\nunknown error {secret}\n", encoding="utf-8")
    (leaf / "stderr.txt").write_text(f"Authorization: Bearer {secret}\nHTTP 401 Unauthorized\n", encoding="utf-8")
    (leaf / "_run-metrics.json").write_text(json.dumps({"api_calls": 1, "failed_api_calls": 1, "usage_complete": False, "prompt": secret, "models": [secret]}), encoding="utf-8")
    original = Path.open
    reads = []

    def checked_open(path, *args, **kwargs):
        if path.is_relative_to(source):
            assert path.name in {"_run-manifest.json", "_cli-failure-diagnostic.json", "_run-metrics.json"}
            reads.append(path.name)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    COLLECTOR.collect(source, output)
    raw = (output / "failure-diagnostic.json").read_text()
    value = json.loads(raw)
    for excluded in (secret, "PROMPT", "Authorization", "private.example", "unknown error", "401"):
        assert excluded not in raw
    assert value["diagnostic"]["cli"]["observations"][0]["status_code"] == 403
    assert value["diagnostic"]["process"]["exit_code"] == 1
    assert value["diagnostic"]["engine"]["code"] == "telemetry_invalid"
    assert value["diagnostic"]["cli"]["cause"] == "unknown"
    assert value["metrics"]["api_calls"] == 1
    assert value["metrics"]["usage_complete"] is False
    assert reads.count("_cli-failure-diagnostic.json") == COLLECTOR.LEAF_COUNT
    assert list(output.iterdir()) == [output / "failure-diagnostic.json"]
    assert len(raw.encode()) <= COLLECTOR.DIAGNOSTIC_MAX_BYTES


def test_missing_manifest_is_explicit_not_a_text_fallback(tmp_path: Path) -> None:
    COLLECTOR.collect(tmp_path / "missing", tmp_path / "out")
    value = json.loads((tmp_path / "out" / "failure-diagnostic.json").read_text())
    assert value["availability"] == "manifest_unavailable"
    assert value["diagnostic"] is None
    assert value["metrics"] is None


@pytest.mark.parametrize("bad", ['"secret"', "-1", "true", "NaN", "Infinity", "1e999", str(2**63)])
def test_rejects_non_numeric_or_invalid_metrics(inputs, bad: str) -> None:
    source, leaf, output = inputs
    (leaf / "_run-metrics.json").write_text('{"usage_complete":false,"api_calls":' + bad + "}", encoding="utf-8")
    with pytest.raises(ValueError, match=r"Invalid scalar diagnostic metric|Nonfinite diagnostic number"):
        COLLECTOR.collect(source, output)
    assert not (output / "failure-diagnostic.json").exists()


@pytest.mark.parametrize("link_method", ["is_symlink", "is_junction"])
def test_rejects_symbolic_link_inputs(inputs, monkeypatch: pytest.MonkeyPatch, link_method: str) -> None:
    source, _, output = inputs
    monkeypatch.setattr(Path, link_method, lambda path: path.name == "leaf-results")
    with pytest.raises(ValueError, match="Symbolic links and junctions"):
        COLLECTOR.collect(source, output)
    assert not (output / "failure-diagnostic.json").exists()


@pytest.mark.parametrize("status", range(400, 600))
def test_all_http_error_statuses(diagnostic, status: int) -> None:
    diagnostic["cli"]["observations"][0]["status_code"] = status
    assert COLLECTOR.project_diagnostic(diagnostic, 1)["cli"]["observations"][0]["status_code"] == status


@pytest.mark.parametrize(("field", "allowed"), list(COLLECTOR.MODEL_FIELDS.items()))
def test_all_fixed_model_enums(diagnostic, field, allowed) -> None:
    for item in allowed:
        diagnostic["cli"]["observations"][0][field] = item
        assert COLLECTOR.project_diagnostic(diagnostic, 1)["cli"]["observations"][0][field] == item


@pytest.mark.parametrize("kind", COLLECTOR.SESSION_TYPES)
def test_all_mapped_session_categories(diagnostic, kind) -> None:
    diagnostic["cli"]["observations"] = [{"type": "session.error", "status_code": None, "status_state": "unavailable", "errorType": kind}]
    assert COLLECTOR.project_diagnostic(diagnostic, 1)["cli"]["observations"][0]["errorType"] == kind


@pytest.mark.parametrize("status", [True, False, 403.0, 403.5, "403", 399, 600, None])
def test_rejects_invalid_http_numbers(diagnostic, status) -> None:
    diagnostic["cli"]["observations"][0]["status_code"] = status
    with pytest.raises(ValueError, match="Invalid diagnostic integer"):
        COLLECTOR.project_diagnostic(diagnostic, 1)


@pytest.mark.parametrize(
    ("section", "key", "bad"),
    [
        (None, "schema_version", True),
        (None, "schema_version", 2),
        (None, "leaf_ordinal", 2),
        (None, "leaf_ordinal", True),
        ("process", "exit_code", True),
        ("process", "exit_code", 2**31),
        ("process", "timeout_observed", "false"),
        ("process", "signal", "SIGKILL"),
        ("capture", "state", "unknown secret"),
        ("capture", "malformed_records", -1),
        ("capture", "unsupported_records", 65537),
        ("capture", "records_limited", 0),
        ("cli", "cause", "authentication"),
        ("engine", "code", "secret message"),
        ("engine", "stage", "secret stage"),
    ],
)
def test_rejects_unknown_constants_types_and_association(diagnostic, section, key, bad) -> None:
    (diagnostic if section is None else diagnostic[section])[key] = bad
    with pytest.raises(ValueError, match=r"Invalid diagnostic|Diagnostic leaf association mismatch"):
        COLLECTOR.project_diagnostic(diagnostic, 1)


@pytest.mark.parametrize("section", [None, "process", "capture", "cli", "engine", "observation"])
def test_unknown_fields_and_sensitive_shapes_are_not_exported(inputs, diagnostic, section) -> None:
    source, leaf, output = inputs
    target = diagnostic if section is None else diagnostic["cli"]["observations"][0] if section == "observation" else diagnostic[section]
    target["message"] = "PROMPT Authorization: Bearer ghp_" + "Z" * 40 + " https://private.example/secret"
    (leaf / "_cli-failure-diagnostic.json").write_text(json.dumps(diagnostic))
    with pytest.raises(ValueError, match="Unexpected diagnostic fields"):
        COLLECTOR.collect(source, output)
    assert not (output / "failure-diagnostic.json").exists()


@pytest.mark.parametrize(
    "raw",
    [
        '{"schema_version":1,"schema_version":1}',
        '{"nested":{"key":1,"key":2}}',
        '{"data":"PROMPT ghp_secret"}',
        '{"cli":{"observations":[{"type":"assistant.message","content":{"type":"session.error"}}]}}',
        "NaN",
    ],
)
def test_invalid_or_duplicate_json_never_becomes_evidence(inputs, raw: str) -> None:
    source, leaf, output = inputs
    (leaf / "_cli-failure-diagnostic.json").write_text(raw)
    with pytest.raises(ValueError, match=r"Duplicate diagnostic key|Unexpected diagnostic fields|Nonfinite diagnostic number"):
        COLLECTOR.collect(source, output)
    assert not (output / "failure-diagnostic.json").exists()


def test_missing_early_leaf_selects_first_failure_and_records_omissions(inputs, diagnostic) -> None:
    source, leaf, output = inputs
    (leaf / "_cli-failure-diagnostic.json").unlink()
    for ordinal in (2, 3):
        directory = source / "leaf-results" / f"{ordinal:02}-al-domain-{ordinal:02}-review"
        directory.mkdir()
        diagnostic["leaf_ordinal"] = ordinal
        (directory / "_cli-failure-diagnostic.json").write_text(json.dumps(diagnostic))
    COLLECTOR.collect(source, output)
    result = json.loads((output / "failure-diagnostic.json").read_text())
    assert result["diagnostic"]["leaf_ordinal"] == 2
    assert result["diagnostics_available"] == 2
    assert result["diagnostics_omitted"] == 1


@pytest.mark.parametrize("bad", ["../private", "/absolute", "al-domain/secret-review", "al-x-review\n", "al-performance-review"])
def test_plan_traversal_and_duplicate_ids_rejected(inputs, bad) -> None:
    source, _, output = inputs
    manifest = json.loads((source / "_run-manifest.json").read_text())
    manifest["plan"]["leaf_ids"][1] = bad
    (source / "_run-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid diagnostic leaf paths"):
        COLLECTOR.collect(source, output)


def test_exact_input_limit_and_oversize_rejection_remove_stale_artifact(inputs) -> None:
    source, leaf, output = inputs
    path = leaf / "_cli-failure-diagnostic.json"
    raw = path.read_bytes()
    path.write_bytes(raw + b" " * (4096 - len(raw)))
    COLLECTOR.collect(source, output)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="byte limit"):
        COLLECTOR.collect(source, output)
    assert not (output / "failure-diagnostic.json").exists()


def test_missing_diagnostic_cannot_look_like_a_success(inputs) -> None:
    source, leaf, output = inputs
    (leaf / "_cli-failure-diagnostic.json").unlink()
    COLLECTOR.collect(source, output)
    result = json.loads((output / "failure-diagnostic.json").read_text())
    assert result["availability"] == "unavailable"
    assert result["diagnostic"] is None


def test_eight_maximal_observations_and_metrics_fit_artifact_bound(inputs, diagnostic) -> None:
    source, leaf, output = inputs
    event = diagnostic["cli"]["observations"][0]
    for key, allowed in COLLECTOR.MODEL_FIELDS.items():
        event[key] = max(allowed, key=len)
    diagnostic["cli"]["observations"] = [event] * 8
    diagnostic["capture"]["records_limited"] = True
    diagnostic["capture"]["state"] = "truncated"
    (leaf / "_cli-failure-diagnostic.json").write_text(json.dumps(diagnostic))
    (leaf / "_run-metrics.json").write_text(json.dumps({**dict.fromkeys(COLLECTOR.SCALAR_METRICS, 2**63 - 1), "usage_complete": False}))
    COLLECTOR.collect(source, output)
    raw = (output / "failure-diagnostic.json").read_bytes()
    assert len(raw) <= 4096
    assert len(json.loads(raw)["diagnostic"]["cli"]["observations"]) == 8
    diagnostic["cli"]["observations"].append(event)
    with pytest.raises(ValueError, match="Invalid diagnostic observation count"):
        COLLECTOR.project_diagnostic(diagnostic, 1)


@pytest.mark.parametrize("stage", COLLECTOR.STAGES)
@pytest.mark.parametrize("code", COLLECTOR.CODES)
def test_all_engine_stage_code_constants(diagnostic, stage, code) -> None:
    diagnostic["engine"] = {"stage": stage, "code": code}
    assert COLLECTOR.project_diagnostic(diagnostic, 1)["engine"] == diagnostic["engine"]


def test_pre_stream_failure_null_facts_remain_unknown(diagnostic) -> None:
    diagnostic["process"] = {"exit_code": None, "timeout_observed": None, "signal": "unknown"}
    diagnostic["capture"]["state"] = "unavailable"
    diagnostic["cli"]["observations"] = []
    diagnostic["engine"] = {"stage": "process-start", "code": "start_failed"}
    result = COLLECTOR.project_diagnostic(diagnostic, 1)
    assert result["process"] == diagnostic["process"]
    assert result["cli"] == {"cause": "unknown", "observations": []}


def test_cli_rejects_without_echoing_malicious_input(inputs) -> None:
    source, leaf, output = inputs
    secret = "ghp_" + "Z" * 40
    (leaf / "_cli-failure-diagnostic.json").write_text('{"PROMPT":"' + secret)
    completed = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "collect_pr_review_failure.py"), "--source-dir", str(source), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert completed.stdout == ""
    assert completed.stderr.strip() == "Failure diagnostic collection rejected an unsafe or invalid input"
    assert secret not in completed.stderr


def test_failure_workflow_upload_is_explicit_short_lived_and_post_failure_only() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "pr-review-evaluation.yml").read_text())
    steps = workflow["jobs"]["evaluate-with-pr-review"]["steps"]
    collect = next(step for step in steps if step["name"] == "Collect bounded CLI failure diagnostic")
    upload = next(step for step in steps if step["name"] == "Upload bounded CLI failure diagnostic")
    assert collect["if"] == upload["if"] == "always() && steps.evaluate-review.outcome == 'failure' && inputs.review-integration != 'none'"
    assert upload["with"]["retention-days"] == 1
    assert upload["with"]["path"] == "${{ env.EVALUATION_RESULTS_DIR }}/failure-diagnostic/${{ matrix.entry }}/failure-diagnostic.json"
    assert "*" not in upload["with"]["path"]
    assert steps.index(collect) > next(index for index, step in enumerate(steps) if step.get("id") == "evaluate-review")
    action = (ROOT / ".github" / "actions" / "install-agent-harnesses" / "action.yml").read_text()
    assert "4517a6d602700fb0eb5a6f598942028436a7dcaf" in action
    assert "@github/copilot@1.0.88" in action


def test_native_path_probe_is_isolated_and_never_invokes_a_prompt() -> None:
    text = (ROOT / ".github" / "workflows" / "probe-mcp-diagnostics.yml").read_text()
    workflow = yaml.safe_load(text)
    assert workflow.get("on", workflow.get(True)) == {"workflow_dispatch": None}
    assert workflow["permissions"] == {"contents": "read"}
    assert list(workflow["jobs"]) == ["probe"]
    steps = workflow["jobs"]["probe"]["steps"]
    assert len(steps) == 2
    script = steps[1]["run"]
    assert script.count("env -i ") == 2
    assert "@github/copilot@1.0.88" in script
    assert "pathResolvedSessionEventsPath(null, null, home, identifier)" in script
    assert '"prebuilds", "linux-x64", "runtime.node"' in script
    assert '"runtime.linux-x64-gnu.node"' in script
    assert "fs.readSync(descriptor, header, 0, 4, 0)" in script
    for excluded in ("${{ secrets.", "${{ github.token", "upload-artifact", "checkout@", "--prompt", "sessionCreate", "sessionConstruct", "COPILOT_GITHUB_TOKEN", "GH_TOKEN"):
        assert excluded not in text
    assert "console.log(JSON.stringify({ status, ...checks }))" in script
