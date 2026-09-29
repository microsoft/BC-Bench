import hashlib
import os
from pathlib import Path

from bcbench_core import RunIdentity, core_version

from bcbench.types import EvaluationCategory


def make_run_identity(category: EvaluationCategory, dataset_path: Path) -> RunIdentity:
    return RunIdentity(
        core_version=core_version(),
        consumer_revision=os.getenv("BCBENCH_CONSUMER_REVISION") or os.getenv("GITHUB_SHA") or "unrecorded",
        benchmark_id=category.value,
        data_revision=hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        scorer_id=f"{category.value}:{category.core_score}:{category.judge_model or ''}",
    )
