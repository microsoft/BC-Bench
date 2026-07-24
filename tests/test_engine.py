import json
from unittest.mock import patch

import pytest

from bcbench.agent.engine import (
    _bcquality_repo_url,
    _finding_to_comment,
    _findings_to_review_comments,
    _read_run_metrics,
    _write_review_json,
    run_engine_review,
)
from bcbench.exceptions import AgentError
from tests.conftest import create_codereview_entry


class TestEngineFindingMapping:
    """Normalization of the engine's _review-report.json findings into review comments."""

    def test_maps_engine_severity_to_gold_taxonomy(self):
        findings = [
            {"severity": s, "message": "x", "location": {"file": "src/A.al", "line": 3}}
            for s in ("blocker", "major", "minor", "info")
        ]
        got = [c["severity"] for c in _findings_to_review_comments({"findings": findings})]
        assert got == ["critical", "high", "medium", "low"]

    def test_uses_location_line_and_range_end(self):
        finding = {"message": "x", "location": {"file": "src/A.al", "line": 14, "range": {"start-line": 14, "end-line": 17}}}
        comment = _finding_to_comment(finding)
        assert comment == {"file": "src/A.al", "line_start": 14, "line_end": 17, "body": "x"}

    def test_falls_back_to_range_start_line_when_line_missing(self):
        finding = {"message": "x", "location": {"file": "src/A.al", "range": {"start-line": 9}}}
        assert _finding_to_comment(finding)["line_start"] == 9

    def test_skips_findings_missing_file_line_or_message(self):
        findings = [
            {"message": "no location", "location": {}},
            {"location": {"file": "src/A.al", "line": 2}},
            {"message": "   ", "location": {"file": "src/A.al", "line": 3}},
        ]
        assert _findings_to_review_comments({"findings": findings}) == []

    def test_unknown_severity_passes_through_lowercased(self):
        finding = {"severity": "Weird", "message": "x", "location": {"file": "src/A.al", "line": 1}}
        assert _finding_to_comment(finding)["severity"] == "weird"


class TestBcqualityRepoOverride:
    def test_defaults_to_upstream(self, monkeypatch):
        monkeypatch.delenv("BCQUALITY_REPO", raising=False)
        assert _bcquality_repo_url() == "https://github.com/microsoft/BCQuality.git"

    def test_full_url_passthrough(self, monkeypatch):
        monkeypatch.setenv("BCQUALITY_REPO", "https://github.com/fork/BCQuality.git")
        assert _bcquality_repo_url() == "https://github.com/fork/BCQuality.git"

    def test_owner_repo_shorthand_expands(self, monkeypatch):
        monkeypatch.setenv("BCQUALITY_REPO", "fork/BCQuality")
        assert _bcquality_repo_url() == "https://github.com/fork/BCQuality.git"


class TestRunMetrics:
    def test_missing_file_returns_empty(self, tmp_path):
        assert _read_run_metrics(tmp_path) == {}

    def test_malformed_json_returns_empty(self, tmp_path):
        (tmp_path / "_run-metrics.json").write_text("{not json", encoding="utf-8")
        assert _read_run_metrics(tmp_path) == {}

    def test_reads_token_counts(self, tmp_path):
        (tmp_path / "_run-metrics.json").write_text(json.dumps({"prompt_tokens": 5, "completion_tokens": 2}), encoding="utf-8")
        assert _read_run_metrics(tmp_path) == {"prompt_tokens": 5, "completion_tokens": 2}


class TestWriteReviewJson:
    def test_raises_when_report_missing(self, tmp_path):
        (tmp_path / "repo").mkdir()
        with pytest.raises(AgentError):
            _write_review_json(tmp_path, tmp_path / "repo")


class TestRunEngineReview:
    def _script_dir(self, tmp_path):
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "Invoke-LocalReview.ps1").write_text("# stub", encoding="utf-8")
        return scripts

    def test_missing_script_raises(self, tmp_path):
        entry = create_codereview_entry()
        with pytest.raises(AgentError):
            run_engine_review(
                entry=entry,
                model="claude-haiku-4.5",
                repo_path=tmp_path / "repo",
                output_dir=tmp_path / "out",
                engine_scripts_dir=tmp_path / "missing-scripts",
            )

    def test_orchestrates_and_maps_report_metrics_and_versions(self, tmp_path):
        entry = create_codereview_entry()
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        output_dir = tmp_path / "out"
        scripts = self._script_dir(tmp_path)

        def fake_run_local_review(local_review_script, repo, bcquality_root, engine_output_dir, base_ref, model):
            engine_output_dir.mkdir(parents=True, exist_ok=True)
            (engine_output_dir / "_review-report.json").write_text(
                json.dumps({"findings": [{"severity": "major", "message": "boom", "location": {"file": "src/A.al", "line": 5}}]}),
                encoding="utf-8",
            )
            (engine_output_dir / "_run-metrics.json").write_text(
                json.dumps({"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133}),
                encoding="utf-8",
            )

        with (
            patch("bcbench.agent.engine._prepare_bcquality", return_value=(tmp_path / "bcq", "bcqsha")),
            patch("bcbench.agent.engine._commit_patched_worktree", return_value="base"),
            patch("bcbench.agent.engine._run_local_review", side_effect=fake_run_local_review) as run_mock,
            patch("bcbench.agent.engine._git_head", return_value="engsha"),
        ):
            metrics, experiment = run_engine_review(
                entry=entry,
                model="claude-haiku-4.5",
                repo_path=repo_path,
                output_dir=output_dir,
                engine_scripts_dir=scripts,
            )

        run_mock.assert_called_once()
        assert json.loads((repo_path / "review.json").read_text(encoding="utf-8")) == [
            {"file": "src/A.al", "line_start": 5, "body": "boom", "severity": "high"}
        ]
        assert metrics is not None
        assert metrics.prompt_tokens == 111
        assert metrics.completion_tokens == 22
        assert metrics.execution_time >= 0
        assert experiment.custom_agent == "bc-pr-review-engine"
        assert experiment.engine_ref == "engsha"
        assert experiment.bcquality_sha == "bcqsha"
        assert experiment.is_empty() is False
