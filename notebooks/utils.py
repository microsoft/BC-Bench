import json
from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd
from unidiff import PatchSet

from bcbench.results.metrics import pass_at_k, pass_hat_k

# Root paths - all notebooks should use these
NOTEBOOKS_ROOT = Path(__file__).parent
DATASET_PATH = NOTEBOOKS_ROOT.parent / "dataset" / "bcbench.jsonl"

Category = Literal["bug-fix", "test-generation"]


def get_result_folder(category: Category = "bug-fix") -> Path:
    return NOTEBOOKS_ROOT / "result" / category


def get_aggregate_result_folder(category: Category = "bug-fix") -> Path:
    return NOTEBOOKS_ROOT / "aggregate-result" / category


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
    """Load results from a setup folder. Handles Braintrust export format."""
    rows = []
    for jsonl_file in setup_folder.glob("*.jsonl"):
        run_id = jsonl_file.stem
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)

            # Normalize field names (Braintrust uses PascalCase)
            scores = data.get("scores", {})
            metrics = data.get("metrics", {}) or {}
            review = data.get("review", {})
            tool_usage = data.get("ToolUsage") or metrics.get("tool_usage")

            rows.append(
                {
                    "run_id": run_id,
                    # Core fields
                    "instance_id": data.get("InstanceID") or data.get("instance_id"),
                    "project": data.get("Project") or data.get("project"),
                    "resolved": scores.get("ResolutionRate", 0) == 1 if scores else data.get("resolved", False),
                    "build": scores.get("BuildRate", 0) == 1 if scores else data.get("build", False),
                    # Metrics
                    "execution_time": metrics.get("duration") or metrics.get("execution_time"),
                    "llm_duration": metrics.get("llm_duration"),
                    "turn_count": metrics.get("TurnCount") or metrics.get("turn_count"),
                    "total_tokens": metrics.get("total_tokens"),
                    "tool_calls": metrics.get("tool_calls"),
                    "tool_usage": tool_usage,
                    # Review (for failure analysis)
                    "failure_category": review.get("failure_category"),
                    # Output (for diff viewing)
                    "output": data.get("output") or data.get("generated_patch", ""),
                }
            )
    return pd.DataFrame(rows)


def load_all_results(category: Category = "bug-fix") -> dict[str, pd.DataFrame]:
    """Load all results for a category, keyed by setup name."""
    result_folder = get_result_folder(category)
    all_results: dict[str, pd.DataFrame] = {}
    for setup_folder in sorted(result_folder.iterdir()):
        if setup_folder.is_dir():
            df = load_results_df(setup_folder)
            if not df.empty:
                all_results[setup_folder.name] = df
    return all_results


def load_aggregate_results(result_folder: Path | None = None, category: Category = "bug-fix") -> dict[str, pd.DataFrame]:
    """Load aggregate results (one jsonl per setup with multiple runs)."""
    if result_folder is None:
        result_folder = get_aggregate_result_folder(category)

    all_results: dict[str, pd.DataFrame] = {}
    for jsonl_file in sorted(result_folder.glob("*.jsonl")):
        setup_name = jsonl_file.stem
        rows = []
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            run_data = json.loads(line)
            run_id = run_data.get("github_run_id", run_data.get("date"))
            instance_results = run_data.get("instance_results", {})
            for instance_id, resolved in instance_results.items():
                rows.append(
                    {
                        "run_id": run_id,
                        "instance_id": instance_id,
                        "resolved": resolved,
                        "execution_time": run_data.get("average_duration", 0),
                    }
                )
        all_results[setup_name] = pd.DataFrame(rows)
    return all_results


def expand_tool_usage(df: pd.DataFrame) -> pd.DataFrame:
    """Expand tool_usage dict column into separate columns."""
    tool_df = df["tool_usage"].apply(lambda x: pd.Series(x) if x else pd.Series(dtype=int))
    return tool_df.fillna(0).astype(int)


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

    return {
        "n_runs": n_runs,
        "n_instances": n_instances,
        "mean_pct": float(runs_resolved.mean() / n_runs * 100),
        "pass_at_k": _calculate_pass_at_k(pivot, n_runs),
        "pass_hat_k": _calculate_pass_hat_k(pivot, n_runs),
    }


def _calculate_pass_at_k(pivot: pd.DataFrame, k: int) -> float:
    num_samples = len(pivot.columns)
    if num_samples < k:
        return 0.0
    total = sum(pass_at_k(num_samples, int(row.sum()), k) for _, row in pivot.iterrows())
    return total / len(pivot)


def _calculate_pass_hat_k(pivot: pd.DataFrame, k: int) -> float:
    num_trials = len(pivot.columns)
    if num_trials < k:
        return 0.0
    total = sum(pass_hat_k(num_trials, int(row.sum()), k) for _, row in pivot.iterrows())
    return total / len(pivot)


def count_files_in_patch(patch: str) -> int:
    return len(PatchSet(patch))


def count_loc_in_patch(patch: str) -> int:
    patch_set = PatchSet(patch)
    return patch_set.added + patch_set.removed


def extract_localizations_from_patch(patch: str) -> set[str]:
    """
    Extract localization codes from a patch based on BC path patterns.

    BC projects have paths like:
    - App/Apps/<Localization>/<ProjectName>/app/  (NAV repo)
    - App/Layers/<Localization>/<ProjectName>/    (NAV repo)
    - src/Apps/<Localization>/<ProjectName>/      (BCApps repo)

    Where <Localization> is W1, DACH, NA, etc.

    Returns set of localization codes found (e.g., {'W1', 'DACH'}).
    """
    import re

    if not patch:
        return set()

    localizations: set[str] = set()

    # Pattern matches:
    # - App/Apps/<loc>/... or App/Layers/<loc>/... (NAV repo)
    # - src/Apps/<loc>/... (BCApps repo)
    # Localization code is typically 2-4 uppercase letters/digits
    loc_pattern = re.compile(r"(?:App|src)[/\\](?:Apps|Layers)[/\\]([A-Z][A-Z0-9]{1,3})[/\\]", re.IGNORECASE)

    for line in patch.split("\n"):
        # Only check diff header lines that contain file paths
        if line.startswith(("+++", "---", "diff --git")):
            matches = loc_pattern.findall(line)
            # Normalize to uppercase
            localizations.update(m.upper() for m in matches)

    return localizations
