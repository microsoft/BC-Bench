import json
from pathlib import Path

import pytest

from bcbench.agent.copilot.pr_review.agent import _prepare_engine_root, _resolve_bcquality_source, _write_review_json
from bcbench.exceptions import AgentError


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "out"
    out.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    return out, repo


def _write_output(output_dir: Path, text: str) -> None:
    (output_dir / "agent-output.txt").write_text(text, encoding="utf-8")


def _write_engine_shell(root: Path) -> None:
    shell = root / "agents" / "ALReviewAgent" / "scripts" / "Invoke-PRReviewShell.ps1"
    shell.parent.mkdir(parents=True)
    shell.write_text("", encoding="utf-8")


def test_prepare_engine_root_uses_configured_local_path(tmp_path: Path) -> None:
    engine = tmp_path / "local-engine"
    _write_engine_shell(engine)

    with _prepare_engine_root(
        {"engine": {"repo": "microsoft/BC-ALAgents", "ref": "main", "local_path": str(engine)}},
        tmp_path / "clone",
    ) as resolved:
        assert resolved == engine


def test_prepare_engine_root_environment_override_takes_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = tmp_path / "configured"
    override = tmp_path / "override"
    _write_engine_shell(configured)
    _write_engine_shell(override)
    monkeypatch.setenv("BC_PR_REVIEW_ROOT", str(override))

    with _prepare_engine_root(
        {"engine": {"local_path": str(configured)}},
        tmp_path / "clone",
        engine_local_path=str(configured),
    ) as resolved:
        assert resolved == override


def test_prepare_engine_root_clones_configured_ref_and_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "engine"
    configured_local = tmp_path / "configured-local"
    clone_args: list[object] = []
    _write_engine_shell(configured_local)

    def fake_clone(repo: str, revision: str, target: Path) -> None:
        clone_args.extend([repo, revision, target])
        _write_engine_shell(target)

    monkeypatch.delenv("BC_PR_REVIEW_ROOT", raising=False)
    monkeypatch.setattr("bcbench.agent.copilot.pr_review.agent.clone_repo_at_revision", fake_clone)

    with _prepare_engine_root(
        {"engine": {"repo": "contoso/BC-ALAgents", "ref": "feature/review", "local_path": str(configured_local)}},
        destination,
        engine_repo="fabrikam/BC-ALAgents",
        engine_ref="experiment/engine",
    ) as resolved:
        assert resolved == destination
        assert destination.exists()

    assert clone_args == ["fabrikam/BC-ALAgents", "experiment/engine", destination]
    assert not destination.exists()


def test_prepare_engine_root_cleans_up_failed_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    destination = tmp_path / "engine"

    def failed_clone(repo: str, revision: str, target: Path) -> None:
        target.mkdir(parents=True)
        (target / "partial").write_text("", encoding="utf-8")
        raise RuntimeError(f"Could not clone {repo}@{revision}")

    monkeypatch.delenv("BC_PR_REVIEW_ROOT", raising=False)
    monkeypatch.setattr("bcbench.agent.copilot.pr_review.agent.clone_repo_at_revision", failed_clone)

    with (
        pytest.raises(RuntimeError, match="Could not clone"),
        _prepare_engine_root(
            {"engine": {"repo": "contoso/BC-ALAgents", "ref": "feature/review"}},
            destination,
        ),
    ):
        pass

    assert not destination.exists()


def test_remote_bcquality_override_ignores_configured_local_path() -> None:
    resolved = _resolve_bcquality_source(
        {"bcquality": {"repo": "microsoft/BCQuality", "ref": "main", "local_path": "C:/local/BCQuality"}},
        bcquality_ref="feature/knowledge",
        bcquality_repo=None,
        bcquality_local_path=None,
    )

    assert resolved == ("feature/knowledge", "microsoft/BCQuality", None)


def test_local_bcquality_override_uses_configured_remote_defaults() -> None:
    resolved = _resolve_bcquality_source(
        {"bcquality": {"repo": "microsoft/BCQuality", "ref": "main", "local_path": None}},
        bcquality_ref=None,
        bcquality_repo=None,
        bcquality_local_path="C:/local/BCQuality",
    )

    assert resolved == ("main", "microsoft/BCQuality", "C:/local/BCQuality")


def test_conflicting_bcquality_cli_sources_raise() -> None:
    with pytest.raises(AgentError, match="cannot be combined"):
        _resolve_bcquality_source(
            {"bcquality": {}},
            bcquality_ref="feature/knowledge",
            bcquality_repo=None,
            bcquality_local_path="C:/local/BCQuality",
        )


def test_valid_empty_findings_is_a_clean_review(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, json.dumps({"outcome": "completed", "outcome-reason": "", "findings": []}))
    assert _write_review_json(out, repo) == 0
    assert json.loads((repo / "review.json").read_text(encoding="utf-8")) == []


def test_findings_are_mapped(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    report = {
        "outcome": "completed",
        "findings": [{"severity": "High", "location": {"file": "src/Foo.al", "line": 42}, "message": "x", "domain": "ui"}],
    }
    _write_output(out, json.dumps(report))
    assert _write_review_json(out, repo) == 1


def test_missing_agent_output_raises(tmp_path: Path) -> None:
    out, repo = _dirs(tmp_path)
    with pytest.raises(AgentError, match="did not produce"):
        _write_review_json(out, repo)


@pytest.mark.parametrize("text", ["", "   ", "not json", "[]"])
def test_invalid_output_raises_instead_of_clean_review(tmp_path: Path, text: str) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, text)
    with pytest.raises(AgentError, match="empty or not a valid"):
        _write_review_json(out, repo)
    assert not (repo / "review.json").exists()


@pytest.mark.parametrize("report", [{"outcome": "failed"}, {"outcome": "dispatch", "findings": None}, {"findings": "nope"}])
def test_malformed_report_raises_instead_of_clean_review(tmp_path: Path, report: dict) -> None:
    out, repo = _dirs(tmp_path)
    _write_output(out, json.dumps(report))
    with pytest.raises(AgentError, match="no findings list"):
        _write_review_json(out, repo)
    assert not (repo / "review.json").exists()
