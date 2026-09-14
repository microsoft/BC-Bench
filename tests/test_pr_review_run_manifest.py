import json
from copy import deepcopy
from pathlib import Path

import pytest

from bcbench.agent.pr_review.run_manifest import load_run_manifest, validate_run_manifest
from bcbench.exceptions import AgentError

ENGINE_COMMIT = "e" * 40
BCQUALITY_COMMIT = "b" * 40
CLI_VERSION = "1.0.83"


def _metrics(model: str) -> dict:
    return {
        "cli_version": CLI_VERSION,
        "models": [model],
        "usage_complete": True,
        "malformed_records": 0,
        "total_tokens": 10,
    }


def _process(role: str, ordinal: int, skill_id: str, model: str) -> dict:
    return {
        "role": role,
        "ordinal": ordinal,
        "skill_id": skill_id,
        "requested_model": model,
        "observed_models": [model],
        "status": "completed",
        "started_at": "2026-09-14T12:00:00.0000000Z",
        "completed_at": "2026-09-14T12:00:01.0000000Z",
        "duration_seconds": 1.0,
        "exit_code": 0,
        "report_path": f"{role}-results/{ordinal}/_review-report.json",
        "failure_reason": None,
        "metrics": _metrics(model),
    }


def valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "status": "completed",
        "started_at": "2026-09-14T12:00:00.0000000Z",
        "completed_at": "2026-09-14T12:00:03.0000000Z",
        "failure_reason": None,
        "engine": {
            "repository": "microsoft/BC-ALAgents",
            "commit": ENGINE_COMMIT,
            "agent_version": "1.6.6",
        },
        "bcquality": {
            "commit": BCQUALITY_COMMIT,
            "source_snapshot": "a" * 64,
        },
        "configuration": {
            "copilot_cli_version": CLI_VERSION,
            "root_model": "claude-sonnet-5",
            "leaf_model": "gpt-5.4",
            "leaf_execution": "serial",
            "max_leaf_concurrency": 4,
            "cli_timeout_minutes": 30,
            "minimum_severity": "Medium",
            "agent_minimum_severity": "Medium",
            "review_source": "local",
        },
        "plan": {
            "skill_id": "al-code-review",
            "leaf_count": 2,
            "leaf_ids": ["al-performance-review", "al-security-review"],
        },
        "processes": [
            _process("leaf", 1, "al-performance-review", "gpt-5.4"),
            _process("leaf", 2, "al-security-review", "gpt-5.4"),
            _process("root", 3, "al-code-review", "claude-sonnet-5"),
        ],
    }


def _load(tmp_path: Path, payload: dict):
    path = tmp_path / "_run-manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_run_manifest(path)


def _validate(manifest) -> None:
    validate_run_manifest(
        manifest,
        engine_commit=ENGINE_COMMIT,
        bcquality_commit=BCQUALITY_COMMIT,
        cli_version=CLI_VERSION,
        root_model="claude-sonnet-5",
        leaf_model="gpt-5.4",
        leaf_execution="serial",
        max_leaf_concurrency=4,
    )


def test_accepts_exact_pinned_runtime(tmp_path: Path) -> None:
    _validate(_load(tmp_path, valid_manifest()))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data.update(status="failed"), "status='failed'"),
        (lambda data: data["engine"].update(commit="f" * 40), "engine.commit"),
        (lambda data: data["bcquality"].update(commit="f" * 40), "bcquality.commit"),
        (lambda data: data["configuration"].update(leaf_model="gpt-5.6-luna"), "leaf_model"),
        (lambda data: data["processes"][0].update(observed_models=["gemini-3.6-flash"]), "model telemetry"),
        (lambda data: data["processes"][0]["metrics"].update(usage_complete=False), "process metrics"),
        (lambda data: data["processes"].reverse(), "process ordinals"),
    ],
)
def test_rejects_contaminated_or_incomplete_runtime(tmp_path: Path, mutation, message: str) -> None:
    payload = deepcopy(valid_manifest())
    mutation(payload)

    with pytest.raises(AgentError, match=message):
        _validate(_load(tmp_path, payload))
