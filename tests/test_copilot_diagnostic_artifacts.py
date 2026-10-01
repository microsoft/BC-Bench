from fnmatch import fnmatchcase
from pathlib import Path

import pytest
import yaml

from bcbench.agent.shared.mcp_diagnostics import SafeDiagnosticSnapshot
from bcbench.config import get_config

WORKFLOWS = Path(__file__).parents[1] / ".github" / "workflows"


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def test_diagnostics_upload_is_scoped_and_available_on_failure():
    workflow = _workflow("copilot-evaluation.yml")
    steps = workflow["jobs"]["evaluate-with-copilot-cli"]["steps"]
    uploads = [step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@")]
    results, diagnostics = uploads

    assert results["with"]["name"] == "evaluation-results-${{ github.run_id }}-${{ matrix.entry }}"
    assert results["with"]["path"] == "${{ env.EVALUATION_RESULTS_DIR }}/**/*.jsonl"
    assert diagnostics["if"] == "${{ always() && inputs.al-mcp }}"
    assert diagnostics["with"]["name"] == "al-mcp-diagnostics-${{ github.run_id }}-${{ matrix.entry }}"
    assert diagnostics["with"]["path"] == "${{ env.EVALUATION_RESULTS_DIR }}/**/diagnostics/al-mcp.json"
    assert diagnostics["with"]["if-no-files-found"] == "warn"
    assert diagnostics["with"]["retention-days"] == "${{ inputs.test-run && 1 || 7 }}"
    assert "include-hidden-files" not in diagnostics["with"]


def test_diagnostic_file_never_matches_evaluation_result_globs(tmp_path: Path):
    root = tmp_path / "evaluation_results"
    run_dir = root / "1234"
    snapshot = SafeDiagnosticSnapshot(run_dir)
    result = run_dir / "microsoftInternal__NAV-1234.jsonl"
    result.write_text("{}\n", encoding="utf-8")
    (run_dir / "copilot.log").write_text("sensitive raw log", encoding="utf-8")
    snapshot.path.with_suffix(".pending").write_text("unfinished snapshot", encoding="utf-8")

    assert list(root.glob("**/diagnostics/al-mcp.json")) == [snapshot.path]
    assert list(root.glob("**/*.jsonl")) == [result]
    assert list(run_dir.rglob(f"*{get_config().file_patterns.result_pattern}")) == [result]


@pytest.mark.parametrize("name", ["copilot-evaluation.yml", "claude-evaluation.yml", "pr-review-evaluation.yml", "bcal-evaluation.yml"])
def test_summary_download_includes_all_result_artifacts_but_no_diagnostics(name: str):
    summary_steps = _workflow("summarize-results.yml")["jobs"]["summarize-results"]["steps"]
    download = next(step for step in summary_steps if step.get("uses", "").startswith("actions/download-artifact@"))
    pattern = download["with"]["pattern"]
    assert pattern == "evaluation-results-*"
    assert download["with"]["merge-multiple"] is True
    assert not fnmatchcase("al-mcp-diagnostics-1234-microsoftInternal__NAV-1234", pattern)

    jobs = _workflow(name)["jobs"]
    artifact_names = [
        step["with"]["name"]
        for job in jobs.values()
        for step in job.get("steps", [])
        if step.get("uses", "").startswith("actions/upload-artifact@") and step["with"]["name"].startswith("evaluation-results-")
    ]
    assert artifact_names
    assert all(fnmatchcase(artifact, pattern) for artifact in artifact_names)
