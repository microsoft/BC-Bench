import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("failure_evidence", ROOT / "tools" / "collect_pr_review_failure.py")
assert SPEC is not None
assert SPEC.loader is not None
COLLECTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTOR)


def test_failure_projection_never_retains_raw_text_or_unknown_metrics(tmp_path: Path) -> None:
    source = tmp_path / "source"
    leaf = source / "leaf-results" / "01-al-performance-review"
    leaf.mkdir(parents=True)
    secret = "ghp_" + "Z" * 40
    (leaf / "stdout.txt").write_text(f"PROMPT: {secret}\nhttps://private.example/?token={secret}\nunknown error {secret}\n", encoding="utf-8")
    (leaf / "stderr.txt").write_text(f"\x1b[31mHTTP 403 Forbidden\x1b[0m\nAuthorization: Bearer {secret}\nmodel not available\n", encoding="utf-8")
    (leaf / "_run-metrics.json").write_text(json.dumps({"api_calls": 1, "failed_api_calls": 1, "usage_complete": False, "prompt": secret, "models": [secret]}), encoding="utf-8")
    output = tmp_path / "output"
    COLLECTOR.collect(source, output)
    raw = (output / "failure-diagnostic.json").read_text()
    value = json.loads(raw)
    for excluded in (secret, "PROMPT", "Authorization", "private.example", "unknown error"):
        assert excluded not in raw
    assert value["outputs"]["stderr"]["http_statuses"] == [403]
    assert value["outputs"]["stderr"]["signals"] == ["access_denied", "model_unavailable"]
    assert value["metrics"]["api_calls"] == 1
    assert value["metrics"]["usage_complete"] is False
    assert list(output.iterdir()) == [output / "failure-diagnostic.json"]


def test_stream_limit_and_missing_outputs(tmp_path: Path) -> None:
    projected = COLLECTOR.project_output(b"x" * (COLLECTOR.MAX_BYTES + 1) + b"HTTP 401 Unauthorized")
    assert projected["truncated"] is True
    assert projected["scanned_bytes"] == COLLECTOR.MAX_BYTES
    assert projected["signals"] == []
    COLLECTOR.collect(tmp_path / "missing", tmp_path / "out")
    assert json.loads((tmp_path / "out" / "failure-diagnostic.json").read_text())["outputs"]["stderr"] == {"available": False}


@pytest.mark.parametrize("bad", ['"secret"', "-1", "true", "NaN", "Infinity"])
def test_rejects_non_numeric_or_invalid_metrics(tmp_path: Path, bad: str) -> None:
    leaf = tmp_path / "source" / "leaf-results" / "01-al-performance-review"
    leaf.mkdir(parents=True)
    (leaf / "_run-metrics.json").write_text('{"usage_complete":false,"api_calls":' + bad + "}", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid scalar diagnostic metric"):
        COLLECTOR.collect(tmp_path / "source", tmp_path / "out")
    assert not (tmp_path / "out" / "failure-diagnostic.json").exists()


def test_rejects_symbolic_link_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    monkeypatch.setattr(Path, "is_symlink", lambda path: path.name == "leaf-results")
    with pytest.raises(ValueError, match="Symbolic links"):
        COLLECTOR.collect(source, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_collector_bounds_actual_reads_and_never_opens_other_files(tmp_path: Path) -> None:
    source = tmp_path / "source"
    leaf = source / "leaf-results" / "01-al-performance-review"
    leaf.mkdir(parents=True)
    (leaf / "stdout.txt").write_bytes(b"x" * (COLLECTOR.MAX_BYTES * 2))
    (leaf / "prompt.txt").write_text("private prompt", encoding="utf-8")
    output = tmp_path / "out"
    COLLECTOR.collect(source, output)
    result = json.loads((output / "failure-diagnostic.json").read_text())
    assert result["outputs"]["stdout"]["truncated"] is True
    assert result["outputs"]["stdout"]["scanned_bytes"] == COLLECTOR.MAX_BYTES
    assert "private prompt" not in (output / "failure-diagnostic.json").read_text()


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
