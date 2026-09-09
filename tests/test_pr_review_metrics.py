import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bcbench.agent.pr_review.metrics import FILTER_REPORT_FILE_NAME, RUN_METRICS_FILE_NAME, _count_available_knowledge, build_pr_review_metrics
from bcbench.dataset.codereview import CodeReviewEntry
from bcbench.exceptions import AgentError
from bcbench.results.bceval_export import write_bceval_results
from bcbench.types import AgentHarness, EvaluationCategory, PRReviewMetrics
from tests.conftest import create_codereview_entry, create_codereview_result


def _run_metrics(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "metrics_source": "copilot-cli-otel",
        "cli_version": "1.0.81-0",
        "wall_time_seconds": 12.346,
        "prompt_tokens": 150,
        "cached_tokens": 60,
        "cache_creation_tokens": 10,
        "completion_tokens": 28,
        "reasoning_tokens": 7,
        "total_tokens": 178,
        "api_calls": 2,
        "failed_api_calls": 1,
        "usage_api_calls": 2,
        "ai_credits": 1.75,
        "premium_requests": 1.75,
        "models": ["gpt-5.4-mini", "gpt-5.6-sol"],
        "usage_complete": True,
        "malformed_records": 0,
    }
    return {**payload, **overrides}


def _write_run_metrics(root: Path, **overrides: object) -> None:
    (root / RUN_METRICS_FILE_NAME).write_text(json.dumps(_run_metrics(**overrides)), encoding="utf-8")
    (root / FILTER_REPORT_FILE_NAME).write_text(json.dumps({"removed": []}), encoding="utf-8")


def test_build_metrics_promotes_public_performance_metrics(tmp_path: Path) -> None:
    _write_run_metrics(tmp_path)

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=12.5)

    assert isinstance(metrics, PRReviewMetrics)
    assert metrics.kind == "pr-review"
    assert metrics.execution_time == 12.5
    assert metrics.prompt_tokens == 150
    assert metrics.completion_tokens == 28
    assert metrics.total_tokens == 178
    assert metrics.ai_credits == 1.75
    assert metrics.cached_tokens == 60
    assert metrics.cache_creation_tokens == 10
    assert metrics.reasoning_tokens == 7
    assert metrics.api_calls == 2
    assert metrics.failed_api_calls == 1
    assert metrics.usage_api_calls == 2
    assert metrics.usage_complete is True
    assert metrics.malformed_records == 0
    assert metrics.knowledge_files == 0
    assert metrics.knowledge_pruned == 0
    assert metrics.knowledge_used is None
    assert metrics.knowledge_suppressed is None
    assert metrics.sub_skills_executed is None
    assert metrics.sub_skills_skipped is None
    assert metrics.copilot_cli_version == "1.0.81-0"


def test_legal_null_optional_fields_and_multiple_models_are_accepted(tmp_path: Path) -> None:
    _write_run_metrics(
        tmp_path,
        cli_version=None,
        wall_time_seconds=None,
        cached_tokens=None,
        cache_creation_tokens=None,
        reasoning_tokens=None,
        ai_credits=None,
        premium_requests=None,
        models=["gpt-5.4-mini", "gpt-5.6-sol"],
    )

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=2.0)

    assert metrics.ai_credits is None
    assert metrics.total_tokens == 178


@pytest.mark.parametrize("has_token_usage", [False, True], ids=["no-chat-spans", "chat-without-billing"])
def test_valid_engine_metrics_without_billing_preserve_unknown_credits_through_export(tmp_path: Path, has_token_usage: bool) -> None:
    # Get-CopilotRunMetrics at engine 159572aad814d6e1022ca8d54e85a6eab7c4d5c6 emits these nullable shapes.
    _write_run_metrics(
        tmp_path,
        cli_version=None,
        wall_time_seconds=2.5,
        prompt_tokens=150 if has_token_usage else None,
        cached_tokens=None,
        cache_creation_tokens=None,
        completion_tokens=28 if has_token_usage else None,
        reasoning_tokens=None,
        total_tokens=178 if has_token_usage else None,
        api_calls=1 if has_token_usage else None,
        failed_api_calls=0 if has_token_usage else None,
        usage_api_calls=1 if has_token_usage else None,
        ai_credits=None,
        premium_requests=None,
        models=[],
        usage_complete=has_token_usage,
        malformed_records=0,
    )

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=2.5)
    assert metrics.ai_credits is None
    assert metrics.total_tokens == (178 if has_token_usage else None)
    result = create_codereview_result(agent_name=AgentHarness.PR_REVIEW, metrics=metrics)
    result.save(tmp_path, "raw-result.jsonl")
    assert json.loads((tmp_path / "raw-result.jsonl").read_text(encoding="utf-8"))["metrics"]["ai_credits"] is None

    with patch.object(CodeReviewEntry, "load", return_value=[create_codereview_entry()]):
        write_bceval_results([result], tmp_path, "run", "export.jsonl", EvaluationCategory.CODE_REVIEW)

    metadata = json.loads((tmp_path / "export.jsonl").read_text(encoding="utf-8"))["metadata"]
    assert metadata["ai_credits"] is None
    assert metadata["prompt_tokens"] == (150 if has_token_usage else 0)
    assert metadata["completion_tokens"] == (28 if has_token_usage else 0)


def test_malformed_records_suppress_all_usage_metrics(tmp_path: Path) -> None:
    _write_run_metrics(
        tmp_path,
        prompt_tokens=25,
        cached_tokens=None,
        cache_creation_tokens=None,
        completion_tokens=5,
        total_tokens=30,
        api_calls=2,
        failed_api_calls=1,
        usage_api_calls=1,
        ai_credits=0.1,
        reasoning_tokens=None,
        premium_requests=None,
        usage_complete=False,
        malformed_records=3,
    )

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=2.0)

    assert metrics.prompt_tokens is None
    assert metrics.completion_tokens is None
    assert metrics.total_tokens is None
    assert metrics.ai_credits is None
    assert metrics.api_calls == 2
    assert metrics.failed_api_calls == 1
    assert metrics.usage_api_calls == 1
    assert metrics.usage_complete is False
    assert metrics.malformed_records == 3


def test_incomplete_usage_suppresses_tokens_but_preserves_exact_credits(tmp_path: Path) -> None:
    _write_run_metrics(
        tmp_path,
        prompt_tokens=25,
        completion_tokens=5,
        total_tokens=30,
        api_calls=2,
        ai_credits=0.1,
        usage_complete=False,
        malformed_records=0,
    )

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=2.0)

    assert metrics.prompt_tokens is None
    assert metrics.completion_tokens is None
    assert metrics.total_tokens is None
    assert metrics.ai_credits == 0.1


def test_missing_run_metrics_raises(tmp_path: Path) -> None:
    with pytest.raises(AgentError, match="run metrics artifact not found"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)


def test_missing_filter_report_preserves_other_diagnostics(tmp_path: Path) -> None:
    _write_run_metrics(tmp_path)
    (tmp_path / FILTER_REPORT_FILE_NAME).unlink()

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)

    assert metrics.prompt_tokens == 150
    assert metrics.knowledge_pruned is None


def test_empty_engine_diagnostics_are_measured_zeros(tmp_path: Path) -> None:
    _write_run_metrics(tmp_path)
    (tmp_path / "al-code-review-findings.json").write_text(
        json.dumps({"findings": [], "subResults": [], "skippedSubSkills": [], "suppressed": []}),
        encoding="utf-8",
    )

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)

    assert metrics.knowledge_used == 0
    assert metrics.knowledge_suppressed == 0
    assert metrics.sub_skills_executed == 0
    assert metrics.sub_skills_skipped == 0


def test_invalid_filter_report_still_raises(tmp_path: Path) -> None:
    _write_run_metrics(tmp_path)
    (tmp_path / FILTER_REPORT_FILE_NAME).write_text("not json", encoding="utf-8")

    with pytest.raises(AgentError, match="Could not read BCQuality filter report"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)


def test_invalid_run_metrics_json_raises(tmp_path: Path) -> None:
    (tmp_path / RUN_METRICS_FILE_NAME).write_text("not json", encoding="utf-8")

    with pytest.raises(AgentError, match="Could not read engine run metrics artifact"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"schema_version": 2},
        {"metrics_source": "console-transcript"},
        {"api_calls": "2"},
        {"usage_complete": 1},
        {"reasoning_tokens": "5"},
        {"premium_requests": "1.0"},
        {"cli_version": 79},
        {"models": ["gpt-5.6-sol", 5]},
        {"unexpected": "field"},
    ],
)
def test_invalid_run_metrics_contract_raises(tmp_path: Path, overrides: dict[str, object]) -> None:
    _write_run_metrics(tmp_path, **overrides)

    with pytest.raises(AgentError, match="does not satisfy schema version 1"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)


def test_missing_run_metrics_key_raises(tmp_path: Path) -> None:
    payload = _run_metrics()
    del payload["models"]
    (tmp_path / RUN_METRICS_FILE_NAME).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AgentError, match="does not satisfy schema version 1"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)


def test_not_applicable_zero_shape_fails_evaluation(tmp_path: Path) -> None:
    _write_run_metrics(
        tmp_path,
        metrics_source="not-applicable",
        cli_version=None,
        wall_time_seconds=0,
        prompt_tokens=0,
        cached_tokens=0,
        cache_creation_tokens=0,
        completion_tokens=0,
        reasoning_tokens=None,
        total_tokens=0,
        api_calls=0,
        failed_api_calls=0,
        usage_api_calls=0,
        ai_credits=0.0,
        premium_requests=None,
        models=[],
        usage_complete=True,
        malformed_records=0,
    )

    with pytest.raises(AgentError, match="must contain AL changes"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=0.25)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cli_version", "1.0.79"),
        ("wall_time_seconds", 1.0),
        ("prompt_tokens", None),
        ("reasoning_tokens", 0),
        ("premium_requests", 0.0),
        ("models", ["gpt-5.6-sol"]),
        ("usage_complete", False),
        ("malformed_records", 1),
    ],
)
def test_not_applicable_rejects_noncanonical_shape(tmp_path: Path, field: str, value: object) -> None:
    not_applicable = {
        "metrics_source": "not-applicable",
        "cli_version": None,
        "wall_time_seconds": 0,
        "prompt_tokens": 0,
        "cached_tokens": 0,
        "cache_creation_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": None,
        "total_tokens": 0,
        "api_calls": 0,
        "failed_api_calls": 0,
        "usage_api_calls": 0,
        "ai_credits": 0.0,
        "premium_requests": None,
        "models": [],
        "usage_complete": True,
        "malformed_records": 0,
        field: value,
    }
    _write_run_metrics(tmp_path, **not_applicable)

    with pytest.raises(AgentError, match="not-applicable metrics have invalid fields"):
        build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)


def test_engine_diagnostics_count_knowledge_and_sub_skills(tmp_path: Path) -> None:
    _count_available_knowledge.cache_clear()
    _write_run_metrics(tmp_path)
    (tmp_path / "microsoft" / "knowledge").mkdir(parents=True)
    (tmp_path / "community" / "knowledge").mkdir(parents=True)
    (tmp_path / "custom" / "skills").mkdir(parents=True)
    (tmp_path / "microsoft" / "knowledge" / "one.md").write_text("one", encoding="utf-8")
    (tmp_path / "community" / "knowledge" / "two.md").write_text("two", encoding="utf-8")
    (tmp_path / "custom" / "skills" / "not-knowledge.md").write_text("skill", encoding="utf-8")
    (tmp_path / FILTER_REPORT_FILE_NAME).write_text(
        json.dumps({"removed": [{"kind": "knowledge"}, {"kind": "knowledge"}, {"kind": "skill"}]}),
        encoding="utf-8",
    )
    (tmp_path / "al-code-review-findings.json").write_text(
        json.dumps(
            {
                "findings": [
                    {
                        "references": [
                            {"path": "microsoft/knowledge/one.md"},
                            {"path": "C:/checkout/bcquality/microsoft/knowledge/one.md"},
                            {"path": "microsoft/skills/not-knowledge.md"},
                            {"path": "microsoft/knowledge/../skills/not-knowledge.md"},
                            {"path": ""},
                        ]
                    }
                ],
                "subResults": [
                    {
                        "references": [
                            {"path": "community/knowledge/two.md"},
                            {"path": "MICROSOFT\\KNOWLEDGE\\ONE.MD"},
                        ]
                    }
                ],
                "skippedSubSkills": [{"name": "one"}, {"name": "two"}],
                "suppressed": [{"path": "custom/knowledge/three.md"}],
            }
        ),
        encoding="utf-8",
    )

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0)

    assert metrics.knowledge_files == 2
    assert metrics.knowledge_pruned == 2
    assert metrics.knowledge_used == 2
    assert metrics.knowledge_suppressed == 1
    assert metrics.sub_skills_executed == 1
    assert metrics.sub_skills_skipped == 2


def test_available_knowledge_count_is_cached_per_checkout(tmp_path: Path) -> None:
    _count_available_knowledge.cache_clear()
    knowledge_root = tmp_path / "microsoft" / "knowledge"
    knowledge_root.mkdir(parents=True)
    (knowledge_root / "one.md").write_text("one", encoding="utf-8")

    assert _count_available_knowledge(tmp_path.resolve()) == 1
    (knowledge_root / "two.md").write_text("two", encoding="utf-8")
    assert _count_available_knowledge(tmp_path.resolve()) == 1


def test_runtime_provenance_is_derived_from_metrics_and_checkout(tmp_path: Path) -> None:
    _write_run_metrics(tmp_path, cli_version="1.0.82")
    engine_root = tmp_path / "engine"
    config = engine_root / "agents" / "ALReviewAgent" / "bcquality.config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "bcquality:\n  repo: https://github.com/microsoft/BCQuality.git\n  ref: " + "a" * 40 + '\n  version: "1.6"\n',
        encoding="utf-8",
    )

    completed = subprocess.CompletedProcess(args=["git"], returncode=0, stdout="b" * 40 + "\n", stderr="")
    with patch("bcbench.agent.pr_review.metrics.subprocess.run", return_value=completed):
        metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0, engine_root=engine_root)

    assert metrics.copilot_cli_version == "1.0.82"
    assert metrics.bcquality_repository == "microsoft/BCQuality"
    assert metrics.bcquality_commit == "b" * 40
    assert metrics.bcquality_version == "1.6"


def test_unavailable_runtime_provenance_does_not_fail_metrics(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    _write_run_metrics(tmp_path, cli_version="1.0.82")

    metrics = build_pr_review_metrics(tmp_path, tmp_path, execution_time=1.0, engine_root=tmp_path / "missing-engine")

    assert metrics.copilot_cli_version == "1.0.82"
    assert metrics.bcquality_repository is None
    assert metrics.bcquality_commit is None
    assert metrics.bcquality_version is None
    assert "BCQuality provenance unavailable" in caplog.text
