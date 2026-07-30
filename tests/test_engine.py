import json
import subprocess
from unittest.mock import patch

import pytest

from bcbench.agent.engine import (
    _bcquality_repo_url,
    _finding_to_comment,
    _findings_to_review_comments,
    _map_severity,
    _prepare_engine,
    _read_run_metrics,
    _run_local_review,
    _write_review_json,
    code_review_uses_engine,
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
            patch("bcbench.agent.engine._ensure_powershell_yaml"),
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


class TestMapSeverity:
    """Every arm resolves severity through the one shared alias table (bcbench.dataset.codereview)."""

    def test_reuses_shared_alias_table(self):
        assert [_map_severity(s) for s in ("blocker", "major", "minor", "info")] == ["critical", "high", "medium", "low"]

    def test_canonical_is_idempotent(self):
        assert _map_severity("Medium") == "medium"

    def test_unknown_passes_through_lowercased(self):
        assert _map_severity("Weird") == "weird"


class TestCodeReviewUsesEngine:
    def test_defaults_to_engine(self, monkeypatch):
        monkeypatch.delenv("BCBENCH_CODE_REVIEW_AGENT", raising=False)
        assert code_review_uses_engine() is True

    def test_copilot_opts_out(self, monkeypatch):
        monkeypatch.setenv("BCBENCH_CODE_REVIEW_AGENT", "copilot")
        assert code_review_uses_engine() is False


class TestPrepareEngine:
    def test_defaults_to_pinned_release(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ENGINE_REF", raising=False)
        with patch("bcbench.agent.engine._clone_at_ref", return_value="sha") as clone:
            _, sha = _prepare_engine(tmp_path, None)
        assert clone.call_args.args[1] == "1.19.4"
        assert sha == "sha"

    def test_env_ref_overrides_pin(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ENGINE_REF", "1.14.4")
        with patch("bcbench.agent.engine._clone_at_ref", return_value="sha") as clone:
            _prepare_engine(tmp_path, None)
        assert clone.call_args.args[1] == "1.14.4"

    def test_local_scripts_dir_skips_clone(self, tmp_path):
        with (
            patch("bcbench.agent.engine._clone_at_ref") as clone,
            patch("bcbench.agent.engine._git_head", return_value="localsha"),
        ):
            scripts, sha = _prepare_engine(tmp_path, tmp_path / "local-scripts")
        clone.assert_not_called()
        assert scripts == tmp_path / "local-scripts"
        assert sha == "localsha"


class TestRunLocalReviewEnv:
    def test_sanitizes_clone_tokens_and_bridges_gh_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BCQUALITY_REPO_TOKEN", "bcq-secret")
        monkeypatch.setenv("ENGINE_REPO_TOKEN", "eng-secret")
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
        captured: dict = {}

        def fake_run(args, **kwargs):
            captured["env"] = kwargs["env"]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            patch("bcbench.agent.engine._pwsh", return_value="pwsh"),
            patch("bcbench.agent.engine.subprocess.run", side_effect=fake_run),
        ):
            _run_local_review(tmp_path / "s.ps1", tmp_path, tmp_path, tmp_path / "out", "base", "claude-haiku-4.5")

        env = captured["env"]
        assert "BCQUALITY_REPO_TOKEN" not in env
        assert "ENGINE_REPO_TOKEN" not in env
        assert env["GH_TOKEN"] == "gh-secret"

    def test_defaults_to_plugin_consumption(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BCQUALITY_CONSUME", raising=False)
        captured: dict = {}

        def fake_run(args, **kwargs):
            captured["env"] = kwargs["env"]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            patch("bcbench.agent.engine._pwsh", return_value="pwsh"),
            patch("bcbench.agent.engine.subprocess.run", side_effect=fake_run),
        ):
            _run_local_review(tmp_path / "s.ps1", tmp_path, tmp_path, tmp_path / "out", "base", "claude-haiku-4.5")

        assert captured["env"]["BCQUALITY_CONSUME"] == "plugin"

    def test_honors_bcquality_consume_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BCQUALITY_CONSUME", "cwd")
        captured: dict = {}

        def fake_run(args, **kwargs):
            captured["env"] = kwargs["env"]
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with (
            patch("bcbench.agent.engine._pwsh", return_value="pwsh"),
            patch("bcbench.agent.engine.subprocess.run", side_effect=fake_run),
        ):
            _run_local_review(tmp_path / "s.ps1", tmp_path, tmp_path, tmp_path / "out", "base", "claude-haiku-4.5")

        assert captured["env"]["BCQUALITY_CONSUME"] == "cwd"
