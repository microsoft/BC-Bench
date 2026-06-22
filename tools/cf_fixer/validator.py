"""Validator — runs dataset validation checks.

Levels:
  1. Fast: JSONL schema/load check (pytest test_counterfactual.py)
  2. Load: Verify entry loads via bcbench CLI
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_BCBENCH_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class ValidationResult:
    status: str  # "success" | "fail" | "skip"
    message: str = ""


def validate_schema(instance_id: str | None = None) -> ValidationResult:
    """Run pytest schema validation for counterfactual entries."""
    cmd = ["uv", "run", "pytest", "tests/test_counterfactual.py", "-v", "--tb=short"]
    if instance_id:
        cmd.extend(["-k", instance_id.replace("__", "_")])

    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_BCBENCH_ROOT,
    )

    status = "success" if result.returncode == 0 else "fail"
    output = result.stdout[-2000:] if result.stdout else ""
    if result.returncode != 0 and result.stderr:
        output += f"\n--- stderr ---\n{result.stderr[-1000:]}"

    return ValidationResult(status=status, message=output)


def validate_dataset_load(instance_id: str) -> ValidationResult:
    """Verify the entry can be loaded via bcbench CLI."""
    cf_num = instance_id.rsplit("__cf-", 1)[-1] if "__cf-" in instance_id else "1"
    cat = f"cf-{cf_num}"

    cmd = ["uv", "run", "bcbench", "dataset", "view", instance_id, "--category", cat]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_BCBENCH_ROOT,
    )

    status = "success" if result.returncode == 0 else "fail"
    msg = result.stdout[-1000:] if status == "success" else result.stderr[-1000:]
    return ValidationResult(status=status, message=msg)
