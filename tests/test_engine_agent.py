import json
from pathlib import Path

import pytest

from bcbench.agent.engine.agent import _write_review_json
from bcbench.exceptions import AgentError


def _dirs(tmp_path: Path) -> tuple[Path, Path]:
    out = tmp_path / "out"
    out.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    return out, repo


def _write_output(output_dir: Path, text: str) -> None:
    (output_dir / "agent-output.txt").write_text(text, encoding="utf-8")


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
