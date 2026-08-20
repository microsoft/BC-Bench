import json
from pathlib import Path

import pytest

from bcbench.agent.pr_review.metrics import FILTER_REPORT_FILE_NAME, build_pr_review_metrics
from bcbench.exceptions import AgentError


def _write_filter_report(root: Path, removed: object) -> None:
    (root / FILTER_REPORT_FILE_NAME).write_text(json.dumps({"removed": removed}), encoding="utf-8")


def test_build_metrics_counts_filtered_knowledge(tmp_path: Path) -> None:
    knowledge = tmp_path / "microsoft" / "knowledge" / "performance"
    knowledge.mkdir(parents=True)
    (knowledge / "one.md").write_text("# One", encoding="utf-8")
    (knowledge / "two.md").write_text("# Two", encoding="utf-8")
    (knowledge / "two.good.al").write_text("", encoding="utf-8")
    (tmp_path / "skills").mkdir()
    (tmp_path / "skills" / "entry.md").write_text("# Entry", encoding="utf-8")
    _write_filter_report(
        tmp_path,
        [
            {"path": "community/knowledge/old.md", "kind": "knowledge", "reason": "layer-disabled"},
            {"path": "community/skills/old.md", "kind": "skill", "reason": "layer-disabled"},
        ],
    )

    metrics = build_pr_review_metrics(tmp_path, execution_time=12.5)

    assert metrics.execution_time == 12.5
    assert metrics.knowledge_files == 2
    assert metrics.knowledge_pruned == 1


def test_missing_filter_report_raises(tmp_path: Path) -> None:
    with pytest.raises(AgentError, match="not found"):
        build_pr_review_metrics(tmp_path, execution_time=1.0)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"removed": "invalid"},
        {"removed": [{"kind": "unknown"}]},
        {"removed": ["invalid"]},
    ],
)
def test_malformed_filter_report_raises(tmp_path: Path, payload: object) -> None:
    (tmp_path / FILTER_REPORT_FILE_NAME).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AgentError, match="filter report"):
        build_pr_review_metrics(tmp_path, execution_time=1.0)


def test_invalid_filter_report_json_raises(tmp_path: Path) -> None:
    (tmp_path / FILTER_REPORT_FILE_NAME).write_text("not json", encoding="utf-8")

    with pytest.raises(AgentError, match="Could not read"):
        build_pr_review_metrics(tmp_path, execution_time=1.0)
