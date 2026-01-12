import json
from pathlib import Path
from typing import TypedDict

import pandas as pd
from unidiff import PatchSet

from bcbench.results.base import create_result_from_json

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
    pass_any_pct: float  # pass@k: resolved in at least 1 run
    pass_majority_pct: float  # resolved in ≥50% of runs
    pass_all_pct: float  # pass^k: resolved in ALL runs
    pass_any_count: int
    pass_majority_count: int
    pass_all_count: int


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
    """Compute pass@k (any) and pass^k (all) metrics across runs.

    Args:
        df: DataFrame with run_id, instance_id, and resolved columns.
        k: Number of runs to consider (uses first k runs). If None, uses all runs.

    Returns:
        PassMetrics with pass@k (lenient), pass^k (strict), and majority voting metrics.
    """
    run_ids = sorted(df["run_id"].unique())
    if k is not None:
        run_ids = run_ids[:k]
    subset_df = df[df["run_id"].isin(run_ids)]

    pivot = subset_df.pivot_table(index="instance_id", columns="run_id", values="resolved", aggfunc=lambda x: x.iloc[0])
    n_runs = len(pivot.columns)
    n_instances = len(pivot)
    runs_resolved = pivot.sum(axis=1)

    pass_all = int((runs_resolved == n_runs).sum())
    pass_majority = int((runs_resolved >= n_runs / 2).sum())
    pass_any = int((runs_resolved >= 1).sum())

    return {
        "n_runs": n_runs,
        "n_instances": n_instances,
        "mean_pct": float(runs_resolved.mean() / n_runs * 100),
        "pass_any_pct": pass_any / n_instances * 100,
        "pass_majority_pct": pass_majority / n_instances * 100,
        "pass_all_pct": pass_all / n_instances * 100,
        "pass_any_count": pass_any,
        "pass_majority_count": pass_majority,
        "pass_all_count": pass_all,
    }


def count_files_in_patch(patch: str) -> int:
    return len(PatchSet(patch))


def count_loc_in_patch(patch: str) -> int:
    patch_set = PatchSet(patch)
    return patch_set.added + patch_set.removed
