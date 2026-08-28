import json
from pathlib import Path

import pytest

from bcbench.agent.pr_review.metrics import RUN_METRICS_FILE_NAME, build_pr_review_metrics
from bcbench.exceptions import AgentError


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


def test_build_metrics_promotes_public_performance_metrics(tmp_path: Path) -> None:
    _write_run_metrics(tmp_path)

    metrics = build_pr_review_metrics(tmp_path, execution_time=12.5)

    assert metrics.execution_time == 12.5
    assert metrics.prompt_tokens == 150
    assert metrics.completion_tokens == 28
    assert metrics.total_tokens == 178
    assert metrics.ai_credits == 1.75


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

    metrics = build_pr_review_metrics(tmp_path, execution_time=2.0)

    assert metrics.ai_credits is None
    assert metrics.total_tokens == 178


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

    metrics = build_pr_review_metrics(tmp_path, execution_time=2.0)

    assert metrics.prompt_tokens is None
    assert metrics.completion_tokens is None
    assert metrics.total_tokens is None
    assert metrics.ai_credits is None


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

    metrics = build_pr_review_metrics(tmp_path, execution_time=2.0)

    assert metrics.prompt_tokens is None
    assert metrics.completion_tokens is None
    assert metrics.total_tokens is None
    assert metrics.ai_credits == 0.1


def test_missing_run_metrics_raises(tmp_path: Path) -> None:
    with pytest.raises(AgentError, match="run metrics artifact not found"):
        build_pr_review_metrics(tmp_path, execution_time=1.0)


def test_invalid_run_metrics_json_raises(tmp_path: Path) -> None:
    (tmp_path / RUN_METRICS_FILE_NAME).write_text("not json", encoding="utf-8")

    with pytest.raises(AgentError, match="Could not read engine run metrics artifact"):
        build_pr_review_metrics(tmp_path, execution_time=1.0)


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
        build_pr_review_metrics(tmp_path, execution_time=1.0)


def test_missing_run_metrics_key_raises(tmp_path: Path) -> None:
    payload = _run_metrics()
    del payload["models"]
    (tmp_path / RUN_METRICS_FILE_NAME).write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AgentError, match="does not satisfy schema version 1"):
        build_pr_review_metrics(tmp_path, execution_time=1.0)


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
        build_pr_review_metrics(tmp_path, execution_time=0.25)


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
        build_pr_review_metrics(tmp_path, execution_time=1.0)
