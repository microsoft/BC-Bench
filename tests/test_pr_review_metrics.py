import json
from pathlib import Path

from bcbench.agent.copilot.pr_review.metrics import (
    FILTER_REPORT_FILE_NAME,
    RUN_METRICS_FILE_NAME,
    TRANSCRIPT_FILE_NAME,
    build_pr_review_metrics,
    parse_filter_report,
    parse_run_metrics,
    parse_transcript_metrics,
)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_parse_run_metrics(tmp_path: Path) -> None:
    path = tmp_path / RUN_METRICS_FILE_NAME
    _write(
        path,
        {
            "prompt_tokens": 1200,
            "completion_tokens": 300,
            "api_calls": 7,
            "estimated_credits": 0.33,
        },
    )

    metrics = parse_run_metrics(path)

    assert metrics == {
        "prompt_tokens": 1200,
        "completion_tokens": 300,
        "total_tokens": 1500,
        "api_calls": 7,
        "estimated_credits": 0.33,
    }


def test_parse_transcript_metrics_from_engine_artifact(tmp_path: Path) -> None:
    path = tmp_path / TRANSCRIPT_FILE_NAME
    path.write_text(
        """err: --- Start of group: Sending request to the AI model ---
err: --- Start of group: Sending request to the AI model ---
err: AI Credits 138 (1m 20s)
err: Tokens     ↑ 1,234,567 (1,000,000 cached) • ↓ 86,543 (500 reasoning)""",
        encoding="utf-8",
    )

    metrics = parse_transcript_metrics(path)

    assert metrics == {
        "prompt_tokens": 1234567,
        "completion_tokens": 86543,
        "total_tokens": 1321110,
        "api_calls": 2,
        "estimated_credits": 138,
    }


def test_parse_filter_report_counts_used_and_pruned_knowledge(tmp_path: Path) -> None:
    knowledge = tmp_path / "content" / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "one.md").write_text("# One", encoding="utf-8")
    (knowledge / "two.md").write_text("# Two", encoding="utf-8")
    report = tmp_path / FILTER_REPORT_FILE_NAME
    _write(report, {"removed": [{"kind": "knowledge"}, {"kind": "skill"}, {"kind": "knowledge"}]})

    metrics = parse_filter_report(report, tmp_path)

    assert metrics == {"knowledge_pruned": 2, "knowledge_used": 2}


def test_build_metrics_degrades_when_side_files_are_missing(tmp_path: Path) -> None:
    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=12.5)

    assert metrics.execution_time == 12.5
    assert metrics.total_tokens is None
    assert metrics.knowledge_used is None
    assert metrics.knowledge_pruned is None


def test_build_metrics_combines_engine_and_knowledge_signals(tmp_path: Path) -> None:
    output = tmp_path / "output"
    output.mkdir()
    bcquality = tmp_path / "bcquality"
    knowledge = bcquality / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "used.md").write_text("# Used", encoding="utf-8")
    _write(
        output / RUN_METRICS_FILE_NAME,
        {
            "prompt_tokens": 1000,
            "completion_tokens": 200,
            "total_tokens": 1200,
            "api_calls": 5,
            "estimated_credits": 0.25,
        },
    )
    _write(bcquality / FILTER_REPORT_FILE_NAME, {"removed": [{"kind": "knowledge"}]})

    metrics = build_pr_review_metrics(output, bcquality, execution_time=8.0)

    assert metrics.total_tokens == 1200
    assert metrics.api_calls == 5
    assert metrics.estimated_credits == 0.25
    assert metrics.knowledge_used == 1
    assert metrics.knowledge_pruned == 1
