import json
from pathlib import Path
from typing import TypedDict

import pandas as pd
from unidiff import PatchSet

from bcbench.results.base import create_result_from_json
from bcbench.results.metrics import pass_at_k, pass_hat_k

RESULT_FOLDER = Path(__file__).parent / "result"


class SummaryStats(TypedDict):
    n_runs: int
    n_instances: int
    avg_execution_time: float
    mean_resolved: float


class PassMetrics(TypedDict):
    n_runs: int
    n_instances: int
    mean_pct: float
    pass_at_k: float
    pass_hat_k: float


def load_results_df(setup_folder: Path) -> pd.DataFrame:
    rows = []
    for jsonl_file in setup_folder.glob("*.jsonl"):
        run_id = jsonl_file.stem
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            r = create_result_from_json(json.loads(line))
            data = r.model_dump()
            metrics = data.pop("metrics", {}) or {}
            tool_usage = metrics.pop("tool_usage", None)
            rows.append({"run_id": run_id, **data, **metrics, "tool_usage": tool_usage})
    return pd.DataFrame(rows)


def expand_tool_usage(df: pd.DataFrame) -> pd.DataFrame:
    """Expand tool_usage dict column into separate columns."""
    tool_df = df["tool_usage"].apply(lambda x: pd.Series(x) if x else pd.Series(dtype=int))
    return tool_df.fillna(0).astype(int)


def get_all_tools(df: pd.DataFrame) -> list[str]:
    """Get all unique tool names from tool_usage column."""
    all_tools: set[str] = set()
    for usage in df["tool_usage"].dropna():
        if usage:
            all_tools.update(usage.keys())
    return sorted(all_tools)


def load_all_results() -> dict[str, pd.DataFrame]:
    all_results: dict[str, pd.DataFrame] = {}
    for setup_folder in sorted(RESULT_FOLDER.iterdir()):
        if setup_folder.is_dir():
            df = load_results_df(setup_folder)
            if not df.empty:
                all_results[setup_folder.name] = df
    return all_results


def compute_summary_stats(df: pd.DataFrame) -> SummaryStats:
    per_run_resolved = df.groupby("run_id")["resolved"].mean() * 100
    return {
        "n_runs": df["run_id"].nunique(),
        "n_instances": df["instance_id"].nunique(),
        "avg_execution_time": float(df["execution_time"].mean()),
        "mean_resolved": float(per_run_resolved.mean()),
    }


def compute_pass_metrics(df: pd.DataFrame, k: int | None = None) -> PassMetrics:
    run_ids = sorted(df["run_id"].unique())
    if k is not None:
        run_ids = run_ids[:k]
    subset_df = df[df["run_id"].isin(run_ids)]

    pivot = subset_df.pivot_table(index="instance_id", columns="run_id", values="resolved", aggfunc=lambda x: x.iloc[0])
    n_runs = len(pivot.columns)
    n_instances = len(pivot)
    runs_resolved = pivot.sum(axis=1)

    pass_at_k_value = _calculate_pass_at_k(pivot, n_runs)
    pass_hat_k_value = _calculate_pass_hat_k(pivot, n_runs)

    return {
        "n_runs": n_runs,
        "n_instances": n_instances,
        "mean_pct": float(runs_resolved.mean() / n_runs * 100),
        "pass_at_k": pass_at_k_value,
        "pass_hat_k": pass_hat_k_value,
    }


def _calculate_pass_at_k(pivot: pd.DataFrame, k: int) -> float:
    num_samples = len(pivot.columns)
    if num_samples < k:
        return 0.0

    total_pass_at_k = 0.0
    for _, row in pivot.iterrows():
        num_correct = int(row.sum())
        total_pass_at_k += pass_at_k(num_samples, num_correct, k)

    return total_pass_at_k / len(pivot)


def _calculate_pass_hat_k(pivot: pd.DataFrame, k: int) -> float:
    num_trials = len(pivot.columns)
    if num_trials < k:
        return 0.0

    total_pass_hat_k = 0.0
    for _, row in pivot.iterrows():
        success_count = int(row.sum())
        total_pass_hat_k += pass_hat_k(num_trials, success_count, k)

    return total_pass_hat_k / len(pivot)


def count_files_in_patch(patch: str) -> int:
    return len(PatchSet(patch))


def count_loc_in_patch(patch: str) -> int:
    patch_set = PatchSet(patch)
    return patch_set.added + patch_set.removed
