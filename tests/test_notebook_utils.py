import json

import pandas as pd
import pytest

from notebooks.utils import compute_pass_metrics, compute_summary_stats, load_results_df


@pytest.mark.parametrize(
    "infrastructure_scores",
    [
        {},
        {"ResolutionRate": None, "BuildRate": None},
    ],
)
def test_infrastructure_null_scores_are_excluded_from_resolution_metrics(tmp_path, infrastructure_scores):
    setup_folder = tmp_path / "setup"
    setup_folder.mkdir()
    rows = [
        {
            "InstanceID": "pass",
            "scores": {"ResolutionRate": 1, "BuildRate": 1},
            "metrics": {"duration": 1},
        },
        {
            "InstanceID": "fail",
            "scores": {"ResolutionRate": 0, "BuildRate": 0},
            "metrics": {"duration": 1},
        },
        {
            "InstanceID": "infrastructure",
            "scores": infrastructure_scores,
            "metadata": {"infrastructure_failure": True},
            "metrics": {"duration": 1},
        },
    ]
    (setup_folder / "run.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows),
        encoding="utf-8",
    )

    results = load_results_df(setup_folder)

    assert results["resolved"].dtype == pd.BooleanDtype()
    assert results["build"].dtype == pd.BooleanDtype()
    assert bool(results.loc[results["instance_id"] == "pass", "resolved"].item()) is True
    assert bool(results.loc[results["instance_id"] == "fail", "resolved"].item()) is False
    assert pd.isna(results.loc[results["instance_id"] == "infrastructure", "resolved"].item())
    assert pd.isna(results.loc[results["instance_id"] == "infrastructure", "build"].item())
    assert compute_summary_stats(results)["mean_resolved"] == 50.0
    assert compute_pass_metrics(results)["mean_pct"] == 50.0


def test_pass_metrics_ignore_null_trials_in_otherwise_evaluated_runs():
    results = pd.DataFrame(
        {
            "run_id": ["run-1", "run-2", "run-3", "run-1", "run-2", "run-3"],
            "instance_id": ["partial", "partial", "partial", "complete", "complete", "complete"],
            "resolved": pd.array([True, False, pd.NA, True, True, True], dtype="boolean"),
        }
    )

    metrics = compute_pass_metrics(results)

    assert metrics["mean_pct"] == 75.0


def test_pass_at_k_excludes_instances_without_k_evaluated_trials():
    results = pd.DataFrame(
        {
            "run_id": ["run-1", "run-2", "run-3", "run-1", "run-2", "run-3"],
            "instance_id": ["partial", "partial", "partial", "complete", "complete", "complete"],
            "resolved": pd.array([True, True, pd.NA, False, False, False], dtype="boolean"),
        }
    )

    metrics = compute_pass_metrics(results)

    assert metrics["pass_at_k"] == 0.0
    assert metrics["pass_hat_k"] == 0.0
