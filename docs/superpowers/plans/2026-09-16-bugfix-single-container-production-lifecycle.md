# Bug-Fix Single-Container Production Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, production-fidelity bug-fix evaluator that uses one Business Central container with verified `S0` and `SF` database checkpoints, independently scores generated tests and fixes, persists per-phase evidence, and destroys the container after evaluation.

**Architecture:** Add a bug-fix-only lifecycle service and CLI composition root rather than extending the shared `EvaluationPipeline`. Reuse existing dataset, agent, patch, build, publication, and exact test-evidence code; add focused result models, trusted workspace/evidence services, a BcContainerHelper checkpoint adapter, and one shared contained-process primitive required to freeze agent descendants and run them under a restricted identity.

**Tech Stack:** Python 3.13, Pydantic 2, Typer, pytest, PowerShell 7, BcContainerHelper 6.x, Windows Job Objects, GitHub Actions, `uv`, Ruff.

---

## Implementation Order and File Map

Implement in this order because later tasks depend on earlier contracts:

1. Result and phase domain models.
2. Bug-fix summaries, leaderboard grouping, and bc-eval metrics.
3. Complete submission freeze and strict audit.
4. Trusted workspaces and atomic evidence.
5. Contained agent process execution.
6. Agent-runner integration.
7. Restricted identity provisioning.
8. Checkpoint and reset-verification adapter.
9. Official phase runner.
10. Production lifecycle state machine and replay mode.
11. CLI commands.
12. Opt-in workflow and cleanup.
13. Real-container rehearsal and fault injection.
14. Documentation and final validation.

### New Python files

- `src\bcbench\evaluate\bugfix_lifecycle\__init__.py` — public lifecycle exports.
- `src\bcbench\evaluate\bugfix_lifecycle\models.py` — immutable workspace, checkpoint, phase, and execution records.
- `src\bcbench\evaluate\bugfix_lifecycle\evidence.py` — hashing and atomic evidence persistence.
- `src\bcbench\evaluate\bugfix_lifecycle\workspace.py` — trusted baseline snapshot and evaluator workspace reconstruction.
- `src\bcbench\evaluate\bugfix_lifecycle\checkpoint.py` — Python bridge to checkpoint/reset PowerShell operations.
- `src\bcbench\evaluate\bugfix_lifecycle\phases.py` — red, gold, fix-build, pair, and benchmark phase execution.
- `src\bcbench\evaluate\bugfix_lifecycle\lifecycle.py` — lifecycle state machine and final cleanup.
- `src\bcbench\commands\bugfix_lifecycle.py` — Copilot and Claude composition-root commands.
- `src\bcbench\agent\shared\contained_process.py` — contained process request/result API.
- `src\bcbench\agent\shared\contained_process_worker.py` — gated child that launches the actual agent command.

### New PowerShell files

- `scripts\Invoke-ContainedProcess.ps1` — restricted-user process launch, Job Object assignment, timeout, and output capture.
- `scripts\BugFixLifecycle.psm1` — restricted identity, checkpoint, inventory, readiness, and cleanup functions.
- `scripts\Setup-BugFixLifecycle.ps1` — opt-in runner/container/workspace provisioning.
- `scripts\Test-BugFixLifecycleCheckpoint.ps1` — restore rehearsal and fault-injection entry point.

### New workflow/action files

- `.github\actions\setup-bugfix-lifecycle\action.yml` — production bug-fix setup wrapper.
- `.github\workflows\bugfix-production-evaluation.yml` — opt-in Copilot/Claude workflow.

### Main modified files

- `src\bcbench\results\base.py`
- `src\bcbench\results\bugfix.py`
- `src\bcbench\results\leaderboard.py`
- `src\bcbench\types.py`
- `src\bcbench\evaluate\bugfix_output.py`
- `src\bcbench\operations\git_operations.py`
- `src\bcbench\agent\shared\env.py`
- `src\bcbench\agent\copilot\cli.py`
- `src\bcbench\agent\claude\agent.py`
- `src\bcbench\commands\__init__.py`
- `src\bcbench\cli.py`
- `src\bcbench\exceptions.py`
- `evaluator\scores.py`
- `tests\conftest.py`
- `docs\bug-fix.md`

## Task 1: Define Bug-Fix Phase and Metric Results

**Files:**
- Modify: `src\bcbench\results\bugfix.py`
- Modify: `tests\conftest.py:102-137`
- Create: `tests\test_bugfix_lifecycle_results.py`

- [ ] **Step 1: Write failing tests for phase-status and metric derivation**

Create `tests\test_bugfix_lifecycle_results.py` with tests covering success, invalid generated test with valid fix, infrastructure coverage, and timeout override:

```python
from bcbench.results.bugfix import (
    BugFixMetricName,
    BugFixPhaseResult,
    BugFixPhaseStatus,
    BugFixResult,
)
from tests.conftest import create_bugfix_result


def phase(status: BugFixPhaseStatus) -> BugFixPhaseResult:
    return BugFixPhaseResult(status=status)


def test_derives_all_successful_metrics() -> None:
    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        test_red=phase(BugFixPhaseStatus.PASSED),
        test_gold=phase(BugFixPhaseStatus.PASSED),
        fix_build=phase(BugFixPhaseStatus.PASSED),
        generated_pair=phase(BugFixPhaseStatus.PASSED),
        benchmark_fix=phase(BugFixPhaseStatus.PASSED),
    )

    assert result.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.GENERATED_PAIR_TRANSITION) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.FIX_BUILD) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.FIX_QUALITY) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.RESOLUTION) is BugFixPhaseStatus.PASSED


def test_invalid_test_does_not_hide_fix_quality() -> None:
    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        test_red=phase(BugFixPhaseStatus.INVALID_SUBMISSION),
        test_gold=phase(BugFixPhaseStatus.INVALID_SUBMISSION),
        fix_build=phase(BugFixPhaseStatus.PASSED),
        generated_pair=phase(BugFixPhaseStatus.INVALID_SUBMISSION),
        benchmark_fix=phase(BugFixPhaseStatus.PASSED),
    )

    assert result.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY) is BugFixPhaseStatus.INVALID_SUBMISSION
    assert result.metric_status(BugFixMetricName.FIX_QUALITY) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.RESOLUTION) is BugFixPhaseStatus.INVALID_SUBMISSION


def test_known_failure_takes_precedence_over_unknown_phase() -> None:
    result = create_bugfix_result(
        runtime_isolation="database-checkpointed-single-container",
        test_red=phase(BugFixPhaseStatus.FAILED),
        test_gold=phase(BugFixPhaseStatus.INFRASTRUCTURE_ERROR),
    )

    assert result.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY) is BugFixPhaseStatus.FAILED


def test_timeout_forces_resolution_failure_only() -> None:
    result = create_bugfix_result(
        timeout=True,
        runtime_isolation="database-checkpointed-single-container",
        test_red=phase(BugFixPhaseStatus.PASSED),
        test_gold=phase(BugFixPhaseStatus.PASSED),
        fix_build=phase(BugFixPhaseStatus.PASSED),
        generated_pair=phase(BugFixPhaseStatus.PASSED),
        benchmark_fix=phase(BugFixPhaseStatus.PASSED),
    )

    assert result.metric_status(BugFixMetricName.FIX_QUALITY) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.RESOLUTION) is BugFixPhaseStatus.FAILED
```

- [ ] **Step 2: Run the tests and confirm the new types are missing**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_results.py -v
```

Expected: collection fails because `BugFixMetricName`, `BugFixPhaseResult`, and `BugFixPhaseStatus` do not exist.

- [ ] **Step 3: Add the phase models and deterministic metric combiner**

Add these domain types to `src\bcbench\results\bugfix.py`:

```python
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class BugFixPhaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INVALID_SUBMISSION = "invalid_submission"
    INFRASTRUCTURE_ERROR = "infrastructure_error"
    NOT_RUN = "not_run"


class BugFixMetricName(StrEnum):
    GENERATED_TEST_VALIDITY = "GeneratedTestValidity"
    GENERATED_PAIR_TRANSITION = "GeneratedPairTransition"
    FIX_BUILD = "FixBuild"
    FIX_QUALITY = "FixQuality"
    RESOLUTION = "Resolution"


class BugFixPhaseResult(BaseModel):
    status: BugFixPhaseStatus = BugFixPhaseStatus.NOT_RUN
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    source_hash: str | None = None
    checkpoint_hash: str | None = None
    requested_tests: tuple[str, ...] = ()
    discovered_tests: tuple[str, ...] = ()
    executed_tests: tuple[str, ...] = ()
    evidence: dict[str, str] = Field(default_factory=dict)


RuntimeIsolation = Literal["package-normalized", "database-checkpointed-single-container"]


def _combine_required_statuses(statuses: tuple[BugFixPhaseStatus, ...]) -> BugFixPhaseStatus:
    if BugFixPhaseStatus.INVALID_SUBMISSION in statuses:
        return BugFixPhaseStatus.INVALID_SUBMISSION
    if BugFixPhaseStatus.FAILED in statuses:
        return BugFixPhaseStatus.FAILED
    if BugFixPhaseStatus.INFRASTRUCTURE_ERROR in statuses:
        return BugFixPhaseStatus.INFRASTRUCTURE_ERROR
    if BugFixPhaseStatus.NOT_RUN in statuses:
        return BugFixPhaseStatus.NOT_RUN
    return BugFixPhaseStatus.PASSED
```

Extend `BugFixResult` with `runtime_isolation`, the five phase records, patch/checkpoint hashes, and `metric_status()`. Keep the existing Boolean fields and derive them in the production result factory rather than deleting them:

```python
    runtime_isolation: RuntimeIsolation = "package-normalized"
    generated_fix_hash: str | None = None
    generated_test_hash: str | None = None
    baseline_checkpoint_hash: str | None = None
    fixed_checkpoint_hash: str | None = None
    test_red: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    test_gold: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    fix_build: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    generated_pair: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)
    benchmark_fix: BugFixPhaseResult = Field(default_factory=BugFixPhaseResult)

    def metric_status(self, metric: BugFixMetricName) -> BugFixPhaseStatus:
        if self.runtime_isolation == "package-normalized":
            if metric in {
                BugFixMetricName.GENERATED_TEST_VALIDITY,
                BugFixMetricName.GENERATED_PAIR_TRANSITION,
            }:
                return BugFixPhaseStatus.NOT_RUN
            if self.infrastructure_failure:
                return BugFixPhaseStatus.INFRASTRUCTURE_ERROR
            if metric is BugFixMetricName.FIX_BUILD:
                return BugFixPhaseStatus.PASSED if self.build else BugFixPhaseStatus.FAILED
            if metric is BugFixMetricName.FIX_QUALITY:
                return BugFixPhaseStatus.PASSED if self.benchmark_test_passed else BugFixPhaseStatus.FAILED
            if metric is BugFixMetricName.RESOLUTION:
                return BugFixPhaseStatus.PASSED if self.resolved else BugFixPhaseStatus.FAILED
        match metric:
            case BugFixMetricName.GENERATED_TEST_VALIDITY:
                return _combine_required_statuses((self.test_red.status, self.test_gold.status))
            case BugFixMetricName.GENERATED_PAIR_TRANSITION:
                return _combine_required_statuses((self.test_red.status, self.generated_pair.status))
            case BugFixMetricName.FIX_BUILD:
                return self.fix_build.status
            case BugFixMetricName.FIX_QUALITY:
                return self.benchmark_fix.status
            case BugFixMetricName.RESOLUTION:
                if self.timeout:
                    return BugFixPhaseStatus.FAILED
                return _combine_required_statuses(
                    (
                        self.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY),
                        self.metric_status(BugFixMetricName.GENERATED_PAIR_TRANSITION),
                        self.metric_status(BugFixMetricName.FIX_QUALITY),
                    )
                )
        raise ValueError(f"Unsupported bug-fix metric: {metric}")
```

- [ ] **Step 4: Extend the test result factory**

Update `create_bugfix_result()` in `tests\conftest.py` to accept all new fields and to set legacy fields from phase success when production phase records are supplied.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_results.py tests\test_result_hierarchy.py -v
```

Expected: all tests pass and existing package-normalized fixtures still deserialize.

- [ ] **Step 6: Commit**

```powershell
git add src\bcbench\results\bugfix.py tests\conftest.py tests\test_bugfix_lifecycle_results.py
git commit -m "Add bug-fix lifecycle result model" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 2: Add Coverage-Aware Bug-Fix Summaries and Export Metrics

**Files:**
- Modify: `src\bcbench\results\base.py`
- Modify: `src\bcbench\results\bugfix.py`
- Modify: `src\bcbench\results\leaderboard.py`
- Modify: `src\bcbench\types.py:320-470`
- Modify: `evaluator\scores.py`
- Modify: `tests\test_evaluation_summary.py`
- Modify: `tests\test_result_hierarchy.py`
- Modify: `tests\test_category_command.py`
- Create: `tests\test_bugfix_lifecycle_summary.py`

- [ ] **Step 1: Write failing coverage and isolation-key tests**

Create `tests\test_bugfix_lifecycle_summary.py`:

```python
from bcbench.results.bugfix import (
    BugFixMetricName,
    BugFixPhaseResult,
    BugFixPhaseStatus,
    BugFixResultSummary,
)
from tests.conftest import create_bugfix_result


def phase(status: BugFixPhaseStatus) -> BugFixPhaseResult:
    return BugFixPhaseResult(status=status)


def test_summary_reports_rate_and_coverage_per_metric() -> None:
    results = [
        create_bugfix_result(
            instance_id="test__success",
            runtime_isolation="database-checkpointed-single-container",
            test_red=phase(BugFixPhaseStatus.PASSED),
            test_gold=phase(BugFixPhaseStatus.PASSED),
            fix_build=phase(BugFixPhaseStatus.PASSED),
            generated_pair=phase(BugFixPhaseStatus.PASSED),
            benchmark_fix=phase(BugFixPhaseStatus.PASSED),
        ),
        create_bugfix_result(
            instance_id="test__unknown",
            runtime_isolation="database-checkpointed-single-container",
            test_red=phase(BugFixPhaseStatus.INFRASTRUCTURE_ERROR),
            test_gold=phase(BugFixPhaseStatus.NOT_RUN),
            fix_build=phase(BugFixPhaseStatus.PASSED),
            benchmark_fix=phase(BugFixPhaseStatus.PASSED),
        ),
    ]

    summary = BugFixResultSummary.from_results(results, run_id="run")

    validity = summary.metric_summaries[BugFixMetricName.GENERATED_TEST_VALIDITY]
    assert validity.successes == 1
    assert validity.determined_failures == 0
    assert validity.unknown == 1
    assert validity.rate == 1.0
    assert validity.coverage == 0.5


def test_runtime_isolation_participates_in_combination_key() -> None:
    checkpointed = BugFixResultSummary.from_results(
        [create_bugfix_result(runtime_isolation="database-checkpointed-single-container")],
        run_id="checkpointed",
    )
    normalized = BugFixResultSummary.from_results(
        [create_bugfix_result(runtime_isolation="package-normalized")],
        run_id="normalized",
    )

    assert checkpointed.combination_key() != normalized.combination_key()


def test_package_normalized_results_keep_legacy_headline() -> None:
    result = create_bugfix_result(
        runtime_isolation="package-normalized",
        resolved=True,
        build=True,
        benchmark_test_passed=True,
    )

    assert result.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY) is BugFixPhaseStatus.NOT_RUN
    assert result.metric_status(BugFixMetricName.FIX_BUILD) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.FIX_QUALITY) is BugFixPhaseStatus.PASSED
    assert result.metric_status(BugFixMetricName.RESOLUTION) is BugFixPhaseStatus.PASSED
```

- [ ] **Step 2: Run the summary tests and verify failure**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_summary.py -v
```

Expected: import fails because `BugFixResultSummary` is not defined.

- [ ] **Step 3: Implement metric summaries and bug-fix dispatch**

Add `BugFixMetricSummary` and `BugFixResultSummary` to `src\bcbench\results\bugfix.py`:

```python
class BugFixMetricSummary(BaseModel):
    successes: int
    determined_failures: int
    unknown: int
    scheduled: int
    rate: float | None
    coverage: float

    @classmethod
    def from_statuses(cls, statuses: tuple[BugFixPhaseStatus, ...]) -> "BugFixMetricSummary":
        successes = statuses.count(BugFixPhaseStatus.PASSED)
        determined_failures = sum(
            status in {BugFixPhaseStatus.FAILED, BugFixPhaseStatus.INVALID_SUBMISSION}
            for status in statuses
        )
        unknown = len(statuses) - successes - determined_failures
        determined = successes + determined_failures
        return cls(
            successes=successes,
            determined_failures=determined_failures,
            unknown=unknown,
            scheduled=len(statuses),
            rate=successes / determined if determined else None,
            coverage=determined / len(statuses) if statuses else 0.0,
        )
```

`BugFixResultSummary` must subclass `ExecutionBasedEvaluationResultSummary`, retain legacy fields, add `runtime_isolation` and `metric_summaries`, and override `combination_key()`.

Change `EvaluationCategory.BUG_FIX.summary_class` to `BugFixResultSummary`.

- [ ] **Step 4: Add a bug-fix leaderboard aggregate**

Add `BugFixLeaderboardAggregate` in `src\bcbench\results\leaderboard.py` as an `ExecutionBasedLeaderboardAggregate` subclass with:

```python
runtime_isolation: str = "package-normalized"
metric_averages: dict[str, float | None] = Field(default_factory=dict)
metric_coverages: dict[str, float] = Field(default_factory=dict)
```

Override `_base_fields()` and `from_runs()` so aggregation rejects mixed isolation modes and averages each run's metric rate and coverage. Change `EvaluationCategory.BUG_FIX.aggregate_class` to this class.

- [ ] **Step 5: Export production metrics to bc-eval**

Extend `BugFixResult.category_metrics` with:

```python
{
    "generated_test_validity_status": self.metric_status(BugFixMetricName.GENERATED_TEST_VALIDITY),
    "generated_pair_transition_status": self.metric_status(BugFixMetricName.GENERATED_PAIR_TRANSITION),
    "fix_build_status": self.metric_status(BugFixMetricName.FIX_BUILD),
    "fix_quality_status": self.metric_status(BugFixMetricName.FIX_QUALITY),
    "resolution_status": self.metric_status(BugFixMetricName.RESOLUTION),
    "runtime_isolation": self.runtime_isolation,
}
```

Broaden the `category_metrics` return annotation in `BaseEvaluationResult` and overrides from `dict[str, int | float | bool]` to `dict[str, int | float | bool | str]`.

Add evaluator classes in `evaluator\scores.py` that map `passed` to `True`, `failed`/`invalid_submission` to `False`, and `infrastructure_error`/`not_run` to `None`. Name them:

- `GeneratedTestValidity`
- `GeneratedPairTransition`
- `FixBuild`
- `FixQuality`
- `Resolution`

Add `EvaluationCategory.production_evaluators` and `EvaluationCategory.production_core_score`. For bug-fix they return:

```python
[
    "generated_test_validity",
    "generated_pair_transition",
    "fix_build",
    "fix_quality",
    "resolution",
]
```

and `"Resolution"`. Other categories raise `ValueError` because they have no production-lifecycle evaluator variant.

Add `production: bool = False` to `category bceval-config`. When true, write `production_evaluators` and `production_core_score`; otherwise preserve the current `evaluators` and `core_score`. Add tests for both branches. The opt-in workflow passes `production: true` to `summarize-results.yml`, which invokes `category bceval-config --production`.

- [ ] **Step 6: Run summary, category, and hierarchy tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_summary.py tests\test_evaluation_summary.py tests\test_result_hierarchy.py tests\test_category_command.py -v
```

Expected: all tests pass, including loading existing package-normalized leaderboard data.

- [ ] **Step 7: Commit**

```powershell
git add src\bcbench\results\base.py src\bcbench\results\bugfix.py src\bcbench\results\leaderboard.py src\bcbench\types.py src\bcbench\commands\category.py evaluator\scores.py tests\test_bugfix_lifecycle_summary.py tests\test_evaluation_summary.py tests\test_result_hierarchy.py tests\test_category_command.py
git commit -m "Add bug-fix lifecycle scoring and coverage" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 3: Freeze and Audit the Complete Submission

**Files:**
- Modify: `src\bcbench\operations\git_operations.py`
- Modify: `src\bcbench\operations\__init__.py`
- Modify: `src\bcbench\evaluate\bugfix_output.py`
- Modify: `src\bcbench\exceptions.py`
- Modify: `tests\test_bugfix_output.py`
- Create: `tests\test_submission_freeze.py`

- [ ] **Step 1: Write failing tests for complete diff capture**

Create `tests\test_submission_freeze.py`:

```python
import subprocess

from bcbench.operations.git_operations import stage_and_get_complete_diff


def test_complete_diff_contains_al_and_forbidden_non_al_changes(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    (repo / "Feature.al").write_text("codeunit 50100 Feature {}\n", encoding="utf-8")
    (repo / "app.json").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "baseline", "-q"], cwd=repo, check=True)

    (repo / "Feature.al").write_text("codeunit 50100 Feature { }\n", encoding="utf-8")
    (repo / "app.json").write_text('{"name":"changed"}\n', encoding="utf-8")

    diff = stage_and_get_complete_diff(repo)

    assert "Feature.al" in diff
    assert "app.json" in diff
```

- [ ] **Step 2: Add strict audit tests to `tests\test_bugfix_output.py`**

Add tests that prove:

- manifest, workflow, Markdown, and evaluator changes are rejected;
- product changes outside dataset-declared product projects are rejected;
- test-project deletions, renames, and removed lines are rejected;
- additions to an existing test file are allowed;
- exactly one new `[Test]` procedure is required;
- generated tests may belong to an existing test project absent from `entry.project_paths`.

Use an explicit API:

```python
result = analyze_generated_bugfix_output(
    repo_path,
    generated_patch,
    allowed_app_projects=("src/Main",),
)
```

- [ ] **Step 3: Run the new tests**

Run:

```powershell
uv run pytest tests\test_submission_freeze.py tests\test_bugfix_output.py -v
```

Expected: failures show that complete diff capture and strict audit parameters are not implemented.

- [ ] **Step 4: Implement complete diff capture**

Add to `src\bcbench\operations\git_operations.py`:

```python
def stage_and_get_complete_diff(repo_path: Path) -> str:
    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "diff", "--cached", "--binary", "--no-ext-diff"],
        cwd=repo_path,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    )
    if not result.stdout:
        raise EmptyDiffError
    return result.stdout
```

Export it from `operations\__init__.py`. Keep the existing AL-only helper for the old evaluator.

- [ ] **Step 5: Implement strict patch audit**

Add a `GeneratedSubmissionError` subclass of `GeneratedOutputError`.

Extend `analyze_generated_bugfix_output()` with `allowed_app_projects`. Before classifying files:

1. Reject any changed path not ending in `.al`.
2. Resolve every `.al` path to an owning project.
3. Require product projects to belong to `allowed_app_projects`.
4. Allow test projects outside dataset metadata only when `is_test_project()` returns true.
5. Reject removed or renamed test files.
6. Reject any removed line in a test-project hunk.
7. Require `sum(len(entry.functionName) for entry in tests) == 1`.

Use this additions-only helper:

```python
def _validate_test_patch_is_additions_only(patched_file: PatchedFile) -> None:
    if patched_file.is_removed or patched_file.is_rename:
        raise GeneratedSubmissionError(f"Generated test changes must be additions only: {patched_file.path}")
    if any(line.is_removed for hunk in patched_file for line in hunk):
        raise GeneratedSubmissionError(f"Generated test changes cannot modify existing test code: {patched_file.path}")
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
uv run pytest tests\test_submission_freeze.py tests\test_bugfix_output.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src\bcbench\operations\git_operations.py src\bcbench\operations\__init__.py src\bcbench\evaluate\bugfix_output.py src\bcbench\exceptions.py tests\test_submission_freeze.py tests\test_bugfix_output.py
git commit -m "Audit complete bug-fix submissions" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 4: Add Trusted Workspaces and Atomic Evidence

**Files:**
- Create: `src\bcbench\evaluate\bugfix_lifecycle\__init__.py`
- Create: `src\bcbench\evaluate\bugfix_lifecycle\models.py`
- Create: `src\bcbench\evaluate\bugfix_lifecycle\evidence.py`
- Create: `src\bcbench\evaluate\bugfix_lifecycle\workspace.py`
- Create: `tests\test_bugfix_lifecycle_evidence.py`
- Create: `tests\test_bugfix_lifecycle_workspace.py`

- [ ] **Step 1: Write failing evidence tests**

Create `tests\test_bugfix_lifecycle_evidence.py`:

```python
import json

from bcbench.evaluate.bugfix_lifecycle.evidence import EvidenceStore, sha256_file, sha256_text
from bcbench.results.bugfix import BugFixPhaseResult, BugFixPhaseStatus


def test_persists_phase_atomically_and_hashes_content(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    phase = BugFixPhaseResult(status=BugFixPhaseStatus.PASSED)

    phase_path = store.save_phase("test_red", phase)

    assert json.loads(phase_path.read_text(encoding="utf-8"))["status"] == "passed"
    assert not list(tmp_path.rglob("*.tmp"))
    assert sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256_file(phase_path)
```

- [ ] **Step 2: Write failing workspace tests**

Create `tests\test_bugfix_lifecycle_workspace.py` with a temporary Git repository. Verify that:

- `capture_trusted_source()` creates a protected bare repository and returns the trusted commit;
- `create_agent_workspace()` and `create_evaluator_workspace()` are separate clones;
- evaluator workspace names contain a random suffix;
- changes in the agent workspace do not appear in a newly created evaluator workspace;
- the disposable baseline path is removed before agent execution.

- [ ] **Step 3: Run tests and verify missing modules**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_evidence.py tests\test_bugfix_lifecycle_workspace.py -v
```

Expected: import failures for the new lifecycle package.

- [ ] **Step 4: Implement immutable lifecycle path records**

In `models.py`, add:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BugFixLifecyclePaths:
    entry_root: Path
    baseline_workspace: Path
    agent_workspace: Path
    agent_logs: Path
    mounted_staging: Path
    evaluator_workspaces: Path
    evidence: Path
    protected_root: Path
    trusted_source: Path
    checkpoints: Path
    final_results: Path


@dataclass(frozen=True)
class TrustedSource:
    repository: Path
    commit: str
```

- [ ] **Step 5: Implement evidence hashing and atomic writes**

`EvidenceStore(tmp_path)` uses `tmp_path\entry\evidence` for ordinary evidence and `tmp_path\protected\final-results` for protected output. `EvidenceStore.save_phase()` writes `entry\evidence\phases\<name>.json`; it must serialize through Pydantic, write to a same-directory temporary file, flush, close, and replace the destination. Add methods for submission patches, checkpoint manifests, arbitrary text diagnostics, and the final result.

Add `protect_artifact(source: Path, kind: str) -> Path`. It computes SHA-256, copies the file to `protected-root\final-results\artifacts\<kind>\<sha256><suffix>`, verifies the copied hash, and returns the protected path. Existing content-addressed files are reused only after their hash is reverified.

- [ ] **Step 6: Implement trusted source capture and clone reconstruction**

`TrustedWorkspaceBuilder` must:

- call `git rev-parse HEAD`;
- clone `baseline_workspace` as a protected bare repository using `git clone --bare`;
- clone agent/evaluator workspaces from the protected bare repository with `--no-hardlinks`;
- check out the trusted commit;
- remove the baseline workspace using the existing targeted `remove_tree()`;
- reject destination paths outside the configured entry root.

Use:

```python
def _is_within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())
```

- [ ] **Step 7: Run focused tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_evidence.py tests\test_bugfix_lifecycle_workspace.py -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src\bcbench\evaluate\bugfix_lifecycle tests\test_bugfix_lifecycle_evidence.py tests\test_bugfix_lifecycle_workspace.py
git commit -m "Add trusted bug-fix workspaces and evidence" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 5: Add Restricted, Process-Tree-Contained Agent Execution

**Files:**
- Create: `src\bcbench\agent\shared\contained_process.py`
- Create: `src\bcbench\agent\shared\contained_process_worker.py`
- Create: `scripts\Invoke-ContainedProcess.ps1`
- Create: `tests\test_contained_process.py`
- Modify: `tests\test_agent_env.py`

- [ ] **Step 1: Write failing contained-process tests**

Create `tests\test_contained_process.py`:

```python
import subprocess
import sys
import time

import pytest

from bcbench.agent.shared.contained_process import ContainedProcessRequest, run_contained_process


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Objects are required")


def test_returns_captured_output(tmp_path) -> None:
    request = ContainedProcessRequest(
        command=(sys.executable, "-c", "print('contained')"),
        cwd=tmp_path,
        env={"PATH": ""},
        timeout_seconds=30,
    )

    result = run_contained_process(request)

    assert result.returncode == 0
    assert result.stdout.strip() == "contained"
    assert result.stderr == ""


def test_timeout_terminates_child_and_grandchild(tmp_path) -> None:
    pid_file = tmp_path / "pids.txt"
    script = (
        "import subprocess,sys,time,pathlib;"
        "child=subprocess.Popen([sys.executable,'-c',"
        "\"import subprocess,sys,time,os,pathlib;"
        "grand=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)']);"
        f"pathlib.Path(r'{pid_file}').write_text(str(os.getpid())+'\\\\n'+str(grand.pid));"
        "time.sleep(300)\"]);"
        "time.sleep(300)"
    )
    request = ContainedProcessRequest(
        command=(sys.executable, "-c", script),
        cwd=tmp_path,
        env=dict(),
        timeout_seconds=2,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        run_contained_process(request)

    child_pid, grandchild_pid = map(int, pid_file.read_text(encoding="utf-8").splitlines())
    time.sleep(1)
    assert not _pid_exists(child_pid)
    assert not _pid_exists(grandchild_pid)
```

Implement `_pid_exists()` in the test with `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` through `ctypes`.

- [ ] **Step 2: Add an allowlist-environment test**

Extend `tests\test_agent_env.py` with:

```python
def test_allowlist_mode_does_not_inherit_evaluator_secrets(monkeypatch) -> None:
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "evaluator-secret")
    monkeypatch.setenv("PATH", "C:\\Windows")

    env = agent_subprocess_env({"COPILOT_GITHUB_TOKEN": "agent-token"}, allowlist=True)

    assert env["PATH"] == "C:\\Windows"
    assert env["COPILOT_GITHUB_TOKEN"] == "agent-token"
    assert "AZURE_CLIENT_SECRET" not in env
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```powershell
uv run pytest tests\test_contained_process.py tests\test_agent_env.py -v
```

Expected: imports and the new `allowlist` parameter fail.

- [ ] **Step 4: Implement the contained-process request/result API**

In `contained_process.py`, define:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WindowsIdentity:
    username: str
    password: str
    domain: str = "."


@dataclass(frozen=True)
class ContainedProcessRequest:
    command: tuple[str, ...]
    cwd: Path
    env: dict[str, str]
    timeout_seconds: int
    identity: WindowsIdentity | None = None


@dataclass(frozen=True)
class ContainedProcessResult:
    returncode: int
    stdout: str
    stderr: str
```

`run_contained_process()` serializes the request to a protected temporary JSON file, invokes `scripts\Invoke-ContainedProcess.ps1`, parses its JSON result, and raises `subprocess.TimeoutExpired` or `subprocess.CalledProcessError` with captured output when required.

Define `AgentExecutionPolicy` in the same module so central domain types do not depend on runtime process code:

```python
@dataclass(frozen=True)
class AgentExecutionPolicy:
    contain_process_tree: bool = False
    restricted_identity: WindowsIdentity | None = None
    allowlist_environment: bool = False
```

- [ ] **Step 5: Implement the gated worker**

`contained_process_worker.py` must:

1. Load a request JSON path and gate path.
2. Wait until the gate file exists.
3. Launch the actual command with the exact supplied environment.
4. Stream the command's stdout/stderr to the worker stdout/stderr.
5. Return the child exit code.

The worker must not read evaluator environment values to construct the child environment.

- [ ] **Step 6: Implement Job Object and restricted-user launch**

In `scripts\Invoke-ContainedProcess.ps1`:

1. Compile a small C# helper with `Add-Type`.
2. Create a Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.
3. Start the gated Python worker with `ProcessStartInfo`.
4. Set `UserName`, `Domain`, and `PasswordInClearText` when an identity is supplied.
5. Clear `ProcessStartInfo.Environment` and add only request values.
6. Redirect worker stdout and stderr to protected temporary files.
7. Assign the worker handle to the Job Object before creating the gate file.
8. Wait for the configured timeout.
9. Call `TerminateJobObject` on timeout.
10. Close the Job Object and return compact JSON with exit code, timeout flag, stdout, and stderr.

The C# helper must expose `CreateKillOnCloseJob()`, `AssignProcess(IntPtr job, IntPtr process)`, `TerminateJob(IntPtr job, uint exitCode)`, and `CloseHandle(IntPtr handle)`.

- [ ] **Step 7: Implement allowlist mode**

Change `agent_subprocess_env()` to accept `allowlist: bool = False`. In allowlist mode, start with:

```python
_AGENT_ENV_ALLOWLIST = frozenset(
    {
        "ALLUSERSPROFILE",
        "APPDATA",
        "COMSPEC",
        "COPILOT_GITHUB_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "GH_TOKEN",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "NODE_PATH",
        "PATH",
        "PATHEXT",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
)
```

Then apply explicit overrides. Preserve current default behavior for existing commands.

- [ ] **Step 8: Resolve the PowerShell script from the repository**

Resolve `Invoke-ContainedProcess.ps1` from `_config.paths.ps_script_path`. Raise `FileNotFoundError` with the resolved path when the checked-out BC-Bench script is missing. Do not change package data.

- [ ] **Step 9: Run focused tests on Windows**

Run:

```powershell
uv run pytest tests\test_contained_process.py tests\test_agent_env.py -v
```

Expected: all tests pass and no child/grandchild survives timeout.

- [ ] **Step 10: Commit**

```powershell
git add src\bcbench\agent\shared\contained_process.py src\bcbench\agent\shared\contained_process_worker.py src\bcbench\agent\shared\env.py scripts\Invoke-ContainedProcess.ps1 tests\test_contained_process.py tests\test_agent_env.py
git commit -m "Contain agent process trees" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 6: Integrate Containment with Copilot and Claude

**Files:**
- Modify: `src\bcbench\agent\copilot\cli.py`
- Modify: `src\bcbench\agent\copilot\agent.py`
- Modify: `src\bcbench\agent\claude\agent.py`
- Modify: `tests\test_copilot_cli.py`
- Modify: `tests\test_claude_agent.py`
- Modify: `tests\test_cli_commands.py`

- [ ] **Step 1: Write failing execution-policy tests**

Import `AgentExecutionPolicy` and `WindowsIdentity` from `bcbench.agent.shared.contained_process`, then add tests proving:

- existing agent commands use the default policy and still call normal subprocess execution;
- production lifecycle callers can pass a contained policy;
- Copilot and Claude pass identical command, working directory, timeout, and allowlisted environment to `run_contained_process`;
- timeout exceptions retain captured output and existing `AgentTimeoutError` behavior.

- [ ] **Step 2: Run focused tests**

Run:

```powershell
uv run pytest tests\test_copilot_cli.py tests\test_claude_agent.py tests\test_cli_commands.py -v
```

Expected: failures for the missing policy and contained execution path.

- [ ] **Step 3: Add optional execution policy parameters**

Add `execution_policy: AgentExecutionPolicy | None = None` to:

- `invoke_copilot()`;
- `run_copilot_agent()`;
- `run_claude_code()`.

When containment is disabled, preserve the current `subprocess.run()` path byte-for-byte except for extracting common result handling.

When enabled:

```python
result = run_contained_process(
    ContainedProcessRequest(
        command=tuple(cmd_args),
        cwd=repo_path,
        env=agent_subprocess_env(
            agent_overrides,
            pass_bc_credentials=category.pass_on_bc_container_credentials,
            allowlist=execution_policy.allowlist_environment,
        ),
        timeout_seconds=_config.timeout.agent_execution,
        identity=execution_policy.restricted_identity,
    )
)
```

Convert non-zero results and timeouts to the same exceptions currently raised by each agent.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
uv run pytest tests\test_copilot_cli.py tests\test_claude_agent.py tests\test_cli_commands.py -v
```

Expected: all tests pass and ordinary evaluation behavior remains unchanged.

- [ ] **Step 5: Commit**

```powershell
git add src\bcbench\agent\copilot\cli.py src\bcbench\agent\copilot\agent.py src\bcbench\agent\claude\agent.py tests\test_copilot_cli.py tests\test_claude_agent.py tests\test_cli_commands.py
git commit -m "Support contained agent execution policies" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 7: Provision Restricted Agent and Evaluator Boundaries

**Files:**
- Create: `scripts\BugFixLifecycle.psm1`
- Create: `scripts\Setup-BugFixLifecycle.ps1`
- Create: `tests\test_bugfix_lifecycle_powershell.py`

- [ ] **Step 1: Write PowerShell contract tests**

Create `tests\test_bugfix_lifecycle_powershell.py` that loads `BugFixLifecycle.psm1` with `pwsh` and verifies exported commands:

```python
import json
import subprocess


def test_bugfix_lifecycle_module_exports_required_commands() -> None:
    script = """
Import-Module .\\scripts\\BugFixLifecycle.psm1 -Force
Get-Command -Module BugFixLifecycle |
    Select-Object -ExpandProperty Name |
    Sort-Object |
    ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=True,
    )
    commands = set(json.loads(result.stdout))
    assert {
        "New-BCBenchAgentIdentity",
        "Remove-BCBenchAgentIdentity",
        "Set-BCBenchWorkspaceAcl",
        "New-BCBenchAgentBcUser",
        "Remove-BCBenchAgentBcUser",
    } <= commands
```

- [ ] **Step 2: Run the contract test**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_powershell.py -v
```

Expected: module import fails.

- [ ] **Step 3: Implement restricted local identity functions**

In `BugFixLifecycle.psm1`:

- create a random entry-scoped local username;
- create the user with `New-LocalUser`;
- never add it to Administrators or `docker-users`;
- grant read/execute access to required installed tools;
- grant modify access only to `agent-workspace` and `agent-logs`;
- restrict `protected-root`, evaluator workspaces, and evidence to the evaluator account and SYSTEM;
- return username/password through a `PSCustomObject`;
- remove or disable the account in cleanup.

Use explicit ACL replacement through `icacls` and verify effective access with a process launched under the restricted user.

- [ ] **Step 4: Implement a distinct Business Central agent user**

Use `New-BcContainerBcUser` with an entry-scoped credential and `-PermissionSetId SUPER`. `SUPER` is required for the current development-endpoint and AL MCP publication behavior; isolation is provided by the separate BC credential, restricted Windows identity, protected evaluator storage, and lack of Docker access.

BcContainerHelper 6.1.18 does not provide `Remove-BcContainerBcUser`. During cleanup, first verify the lifecycle invocation label and recorded Docker ID still own the named container. Then use `Invoke-ScriptInBcContainer` to find the server instance, call `Remove-NAVServerUser -Tenant default -Force`, and verify `Get-NAVServerUser` no longer returns the agent user. This pinned-version equivalent must be implemented by `Remove-BCBenchAgentBcUser`; do not invent or call an unavailable BcContainerHelper command.

The agent BC user must:

- differ from evaluator admin;
- have only the permissions required by the selected MCP/tooling configuration;
- be removed before final container deletion;
- never receive evaluator credentials.

Return an agent `ContainerConfig` separately from the evaluator `ContainerConfig`.

- [ ] **Step 5: Implement setup script outputs**

`Setup-BugFixLifecycle.ps1` must create:

- `entry-root`;
- `baseline-workspace`;
- `agent-workspace`;
- `agent-logs`;
- `mounted-staging`;
- `evaluator-workspaces`;
- `evidence`;
- `protected-root` outside container mounts.

It must clone the dataset repository into `baseline-workspace`, create the container with explicit shared folders, create both identities, and write masked GitHub Actions outputs for every path and agent credential required by the lifecycle command.

- [ ] **Step 6: Run module contract tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_powershell.py -v
```

Expected: all non-admin contract tests pass. Mark tests requiring local-user creation as `integration`.

- [ ] **Step 7: Commit**

```powershell
git add scripts\BugFixLifecycle.psm1 scripts\Setup-BugFixLifecycle.ps1 tests\test_bugfix_lifecycle_powershell.py
git commit -m "Provision restricted bug-fix agent identities" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 8: Implement Checkpoint, Inventory, and Reset Verification

**Files:**
- Modify: `scripts\BugFixLifecycle.psm1`
- Create: `src\bcbench\evaluate\bugfix_lifecycle\checkpoint.py`
- Modify: `src\bcbench\evaluate\bugfix_lifecycle\models.py`
- Modify: `src\bcbench\exceptions.py`
- Create: `tests\test_bugfix_lifecycle_checkpoint.py`

- [ ] **Step 1: Write failing Python adapter tests**

Create `tests\test_bugfix_lifecycle_checkpoint.py` with a fake PowerShell runner. Verify:

- capture stops the service, creates exactly one `.bak`, hashes it, copies it to protected storage, removes staging, and restarts readiness;
- restore verifies the protected hash before staging;
- container ID mismatch is rejected;
- app-inventory mismatch is rejected;
- malformed JSON and non-zero PowerShell exit become `CheckpointInfrastructureError`;
- a failed restore never calls phase execution.

- [ ] **Step 2: Add checkpoint records**

In `models.py`, define:

```python
@dataclass(frozen=True)
class ContainerIdentity:
    container_id: str
    image_id: str
    hostname: str
    mounts: tuple[str, ...]


@dataclass(frozen=True)
class AppInventoryEntry:
    app_id: str
    name: str
    publisher: str
    version: str
    package_id: str | None
    scope: str
    installed: bool
    synchronized: bool
    content_hash: str | None


@dataclass(frozen=True)
class CheckpointManifest:
    name: str
    backup_path: Path
    sha256: str
    database_name: str
    database_folder: str
    container: ContainerIdentity
    apps: tuple[AppInventoryEntry, ...]
```

Add explicit lifecycle infrastructure exceptions to `exceptions.py`:

```python
class BugFixLifecycleInfrastructureError(BCBenchError):
    """Base class for unknown bug-fix lifecycle outcomes."""


class CheckpointInfrastructureError(BugFixLifecycleInfrastructureError):
    """Checkpoint capture, restore, or verification failed."""


class CleanupInfrastructureError(BugFixLifecycleInfrastructureError):
    """Container, identity, or workspace cleanup could not be verified."""
```

- [ ] **Step 3: Add PowerShell checkpoint functions**

Export these functions from `BugFixLifecycle.psm1`:

- `Stop-BCBenchServiceTier`
- `Start-BCBenchServiceTier`
- `Get-BCBenchContainerIdentity`
- `Get-BCBenchDatabaseTopology`
- `Get-BCBenchAppInventory`
- `Backup-BCBenchCheckpoint`
- `Restore-BCBenchCheckpoint`
- `Test-BCBenchReadiness`
- `Remove-BCBenchContainerAndVerify`

`Backup-BCBenchCheckpoint` must call `Backup-BcContainerDatabases`, require one expected `.bak`, run SQL restore-header verification, and emit JSON metadata.

`Restore-BCBenchCheckpoint` must call:

```powershell
Restore-DatabasesInBcContainer `
    -containerName $ContainerName `
    -bakFile $StagedBackup `
    -databaseName $DatabaseName `
    -databaseFolder $DatabaseFolder `
    -sqlTimeout $SqlTimeout
```

Then start the service tier and verify identity, database, company, authentication, endpoint, app inventory, and test discovery.

- [ ] **Step 4: Implement the Python checkpoint manager**

`CheckpointManager.capture(name, expected_apps)` and `restore(manifest, expected_apps)` must:

- keep checkpoint masters under `protected-root\checkpoints`;
- use a fresh child under `mounted-staging`;
- verify SHA-256 before and after every transfer;
- persist the manifest through `EvidenceStore`;
- remove staging in `finally`;
- raise `CheckpointInfrastructureError` on any mismatch;
- never perform package cleanup as fallback.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_checkpoint.py tests\test_bugfix_lifecycle_powershell.py -v
```

Expected: all adapter and module contract tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts\BugFixLifecycle.psm1 src\bcbench\evaluate\bugfix_lifecycle\models.py src\bcbench\evaluate\bugfix_lifecycle\checkpoint.py src\bcbench\exceptions.py tests\test_bugfix_lifecycle_checkpoint.py tests\test_bugfix_lifecycle_powershell.py
git commit -m "Add verified Business Central checkpoints" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 9: Implement the Five Official Evaluation Phases

**Files:**
- Create: `src\bcbench\evaluate\bugfix_lifecycle\phases.py`
- Modify: `src\bcbench\evaluate\bugfix_lifecycle\models.py`
- Create: `tests\test_bugfix_lifecycle_phases.py`

- [ ] **Step 1: Write failing phase-runner tests**

Create `tests\test_bugfix_lifecycle_phases.py` with fake workspace, checkpoint, build, inventory, and test adapters. Cover:

- `test_red` restores `S0`, applies only `T`, publishes tests last, and requires `ALL_FAIL`;
- `test_gold` restores `S0`, applies `G` then `T`, publishes `T` last, and requires `ALL_PASS`;
- `fix_build` restores `S0`, applies only `F`, rejects installed generated-test packages, and captures `SF`;
- `generated_pair` does not restore immediately after `SF` capture and runs after a wrong red outcome when the test executed;
- `benchmark_fix` restores `SF`, proves generated test absence, applies `H`, and runs all benchmark tests;
- a generated build error is `failed`;
- missing JUnit or restore failure is `infrastructure_error`;
- an invalid `T` does not prevent `fix_build` and `benchmark_fix`.

- [ ] **Step 2: Run tests and verify missing phase runner**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_phases.py -v
```

Expected: import failure for `BugFixPhaseRunner`.

- [ ] **Step 3: Define injected operation protocols**

In `phases.py`, define narrow protocols:

```python
class ProjectPublisher(Protocol):
    def build_and_publish(self, repo_path: Path, project_paths: tuple[str, ...]) -> tuple[Path, ...]: ...


class ExactTestRunner(Protocol):
    def run(
        self,
        tests: tuple[TestEntry, ...],
        expectation: TestExpectation,
        repo_path: Path,
    ) -> TestRunSummary: ...
```

Inject `TrustedWorkspaceBuilder`, `CheckpointManager`, `ProjectPublisher`, `ExactTestRunner`, and `EvidenceStore` into `BugFixPhaseRunner`.

- [ ] **Step 4: Implement a shared phase boundary**

Use a helper that records UTC start/end times, maps known exceptions to a phase status, saves the phase record atomically, and returns it:

```python
def _execute_phase(
    self,
    name: str,
    operation: Callable[[], BugFixPhaseResult],
) -> BugFixPhaseResult:
    started_at = datetime.now(UTC)
    try:
        result = operation()
    except GeneratedSubmissionError as error:
        result = BugFixPhaseResult(status=BugFixPhaseStatus.INVALID_SUBMISSION, error_message=str(error))
    except (
        BugFixLifecycleInfrastructureError,
        BuildTimeoutExpired,
        TestInfrastructureError,
    ) as error:
        result = BugFixPhaseResult(status=BugFixPhaseStatus.INFRASTRUCTURE_ERROR, error_message=str(error))
    except (BuildError, TestExecutionError) as error:
        result = BugFixPhaseResult(status=BugFixPhaseStatus.FAILED, error_message=str(error))
    completed = result.model_copy(update={"started_at": started_at, "completed_at": datetime.now(UTC)})
    self._evidence.save_phase(name, completed)
    return completed
```

Do not broadly catch `Exception`; unexpected evaluator defects must propagate after an emergency diagnostic is persisted by the lifecycle.

Phase methods must translate patch failures before they reach `_execute_phase()`:

- failure applying generated `F` or `T` to trusted `O` becomes `GeneratedSubmissionError`;
- failure applying trusted gold `G` or benchmark tests `H` becomes `BugFixLifecycleInfrastructureError`.

- [ ] **Step 5: Implement phase methods**

Add:

- `run_test_red(submission, s0)`
- `run_test_gold(submission, s0, gold_patch)`
- `run_fix_build(submission, s0) -> tuple[BugFixPhaseResult, CheckpointManifest | None]`
- `run_generated_pair(submission, sf, red_result)`
- `run_benchmark_fix(submission, sf, benchmark_patch, benchmark_tests)`

Every method must create a new evaluator workspace from trusted `O`, apply only its declared patches, publish product projects before test projects, verify expected inventory, and include exact requested/discovered/executed identities in its returned phase result.

`ProjectPublisher.build_and_publish()` returns the generated `.app` paths. Protect every official package through `EvidenceStore.protect_artifact()` and include its SHA-256 in phase evidence. In `test_gold`, the `O + G` product package is therefore content-addressed under protected storage before `T` is published; a later replay may reuse it only when the source-state hash and package hash both match.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_phases.py tests\test_bugfix_pipeline.py tests\test_bugfix_output.py -v
```

Expected: all tests pass and the existing package-normalized evaluator remains unchanged.

- [ ] **Step 7: Commit**

```powershell
git add src\bcbench\evaluate\bugfix_lifecycle\phases.py src\bcbench\evaluate\bugfix_lifecycle\models.py tests\test_bugfix_lifecycle_phases.py
git commit -m "Implement checkpointed bug-fix phases" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 10: Implement the Production Lifecycle State Machine and Replay Mode

**Files:**
- Create: `src\bcbench\evaluate\bugfix_lifecycle\lifecycle.py`
- Modify: `src\bcbench\evaluate\bugfix_lifecycle\__init__.py`
- Create: `tests\test_bugfix_production_lifecycle.py`

- [ ] **Step 1: Write failing state-machine tests**

Create `tests\test_bugfix_production_lifecycle.py`. Use fake collaborators to assert exact call order for:

1. full success;
2. invalid generated test with successful independent fix;
3. wrong red outcome with gold, fix, pair, and benchmark still run;
4. `S0` restore infrastructure failure followed by a later independent successful restore;
5. failed `fix_build` causing pair and benchmark `not_run`;
6. agent timeout with all diagnostic phases passing but `Resolution=failed`;
7. replay mode skipping the agent while using the supplied patch;
8. result saved before container destruction;
9. cleanup attempted after unexpected evaluator exception;
10. cleanup failure creating a quarantine marker.

- [ ] **Step 2: Run tests and verify missing lifecycle**

Run:

```powershell
uv run pytest tests\test_bugfix_production_lifecycle.py -v
```

Expected: import failure for `ProductionBugFixLifecycle`.

- [ ] **Step 3: Define the lifecycle request**

Define a lifecycle-specific agent protocol so the shared `AgentRunner` interface remains unchanged:

```python
class ProductionAgentRunner(Protocol):
    def __call__(
        self,
        context: EvaluationContext[BugFixEntry],
        execution_policy: AgentExecutionPolicy,
    ) -> tuple[AgentMetrics | None, ExperimentConfiguration | None]: ...
```

Add an immutable request:

```python
@dataclass(frozen=True)
class BugFixLifecycleRequest:
    context: EvaluationContext[BugFixEntry]
    paths: BugFixLifecyclePaths
    evaluator_container: ContainerConfig
    agent_runtime: AgentRuntimeConfig
    agent_execution_policy: AgentExecutionPolicy
    replay_patch: Path | None = None
```

- [ ] **Step 4: Implement baseline preparation**

The lifecycle must:

1. call `setup_repo_prebuild()` on `baseline_workspace`;
2. build and publish original projects;
3. copy the problem statement and set runtime versions;
4. commit all trusted baseline preparation with `commit_changes()`;
5. record container/app inventory;
6. capture `S0`;
7. capture the protected bare trusted source;
8. create `agent-workspace`;
9. remove `baseline-workspace`.

- [ ] **Step 5: Implement agent execution and freeze**

When `replay_patch` is absent:

- invoke the injected `ProductionAgentRunner` with the restricted execution policy;
- preserve metrics/config on normal completion or timeout;
- after completion or timeout, terminate the contained process group;
- stop the service tier;
- call `stage_and_get_complete_diff(agent_workspace)`;
- save the full patch and SHA-256 before analysis.

When `replay_patch` is present:

- do not invoke an agent;
- read and hash the supplied patch;
- mark execution mode as `replay`;
- leave timeout false.

Analyze the patch against trusted `O` with dataset-declared product projects.

- [ ] **Step 6: Implement phase dependency logic**

The lifecycle executes:

```python
test_red = phases.run_test_red(submission, s0)
test_gold = phases.run_test_gold(submission, s0, entry.patch)
fix_build, sf = phases.run_fix_build(submission, s0)
generated_pair = (
    phases.run_generated_pair(submission, sf, test_red)
    if sf is not None and test_red.executed_tests
    else BugFixPhaseResult(status=BugFixPhaseStatus.NOT_RUN)
)
benchmark_fix = (
    phases.run_benchmark_fix(submission, sf, entry.test_patch, benchmark_tests)
    if sf is not None
    else BugFixPhaseResult(status=BugFixPhaseStatus.NOT_RUN)
)
```

If `T` is invalid, create invalid-submission results for generated-test phases but continue fix phases. If `F` is invalid or absent, mark fix phases invalid/not-run without hiding valid generated-test diagnostics.

- [ ] **Step 7: Implement final result projection**

Construct one `BugFixResult` with:

- runtime isolation `database-checkpointed-single-container`;
- agent timeout metadata;
- all phase records;
- patch/checkpoint hashes;
- legacy Boolean projections;
- `resolved` from `Resolution`;
- `build` from `FixBuild`;
- `infrastructure_failure=True` only when no production metric has a determined outcome, preserving the field for legacy readers without using it for production summary scoring.

Save the result and final evidence manifest before cleanup.

- [ ] **Step 8: Implement guaranteed cleanup**

In `finally`:

1. stop evaluator processes;
2. remove the agent BC user;
3. remove the container and verify absence;
4. remove entry-specific compiler and workspace directories;
5. remove the restricted local user;
6. persist cleanup evidence;
7. create `protected-root\quarantine.json` and raise `CleanupInfrastructureError` if any cleanup verification fails.

- [ ] **Step 9: Run focused state-machine tests**

Run:

```powershell
uv run pytest tests\test_bugfix_production_lifecycle.py tests\test_bugfix_lifecycle_phases.py -v
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```powershell
git add src\bcbench\evaluate\bugfix_lifecycle\lifecycle.py src\bcbench\evaluate\bugfix_lifecycle\__init__.py tests\test_bugfix_production_lifecycle.py
git commit -m "Add bug-fix production lifecycle state machine" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 11: Add Bug-Fix Lifecycle CLI Commands

**Files:**
- Create: `src\bcbench\commands\bugfix_lifecycle.py`
- Modify: `src\bcbench\commands\__init__.py`
- Modify: `src\bcbench\cli.py`
- Modify: `src\bcbench\cli_options.py`
- Modify: `tests\test_cli_commands.py`

- [ ] **Step 1: Write failing CLI tests**

Add tests using `CliRunner`:

```python
def test_bugfix_lifecycle_help_lists_agent_commands() -> None:
    result = runner.invoke(app, ["bugfix-lifecycle", "--help"])

    assert result.exit_code == 0
    assert "copilot" in result.stdout
    assert "claude" in result.stdout


def test_bugfix_lifecycle_rejects_missing_protected_root() -> None:
    result = runner.invoke(
        app,
        [
            "bugfix-lifecycle",
            "copilot",
            "microsoftInternal__NAV-1",
            "--entry-root",
            "C:\\entry",
        ],
    )

    assert result.exit_code != 0
    assert "protected-root" in result.stdout
```

Also test that `--replay-patch` bypasses agent-runner invocation and that both commands inject the correct `AgentHarness`.

- [ ] **Step 2: Run CLI tests**

Run:

```powershell
uv run pytest tests\test_cli_commands.py -v
```

Expected: no such command `bugfix-lifecycle`.

- [ ] **Step 3: Add lifecycle CLI path and identity options**

In `cli_options.py`, add typed options for:

- `EntryRoot`
- `ProtectedRoot`
- `ReplayPatch`
- `AgentOsUsername`
- `AgentOsPassword`
- `AgentBcUsername`
- `AgentBcPassword`

Use environment variables prefixed with `BCBENCH_LIFECYCLE_` and mark password values hidden from help output.

- [ ] **Step 4: Implement a shared private composition function**

In `commands\bugfix_lifecycle.py`, create `_run_lifecycle()` that:

- fixes the category to `EvaluationCategory.BUG_FIX`;
- prepares the run directory;
- constructs evaluator and agent `ContainerConfig` values separately;
- constructs `AgentExecutionPolicy(contain_process_tree=True, restricted_identity=..., allowlist_environment=True)`;
- builds `BugFixLifecyclePaths`;
- constructs `ProductionBugFixLifecycle`;
- injects the selected agent runner;
- supports `replay_patch`.

Expose `copilot` and `claude` Typer commands with their existing model and MCP/LSP options.

- [ ] **Step 5: Register the command group**

Export `bugfix_lifecycle_app` from `commands\__init__.py` and add:

```python
app.add_typer(bugfix_lifecycle_app, name="bugfix-lifecycle")
```

to `cli.py`.

- [ ] **Step 6: Run CLI tests**

Run:

```powershell
uv run pytest tests\test_cli_commands.py tests\test_category_command.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src\bcbench\commands\bugfix_lifecycle.py src\bcbench\commands\__init__.py src\bcbench\cli.py src\bcbench\cli_options.py tests\test_cli_commands.py
git commit -m "Add bug-fix lifecycle commands" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 12: Add the Opt-In Production Workflow

**Implementation notes:** The workflow keeps credentials in the existing setup-exported environment, installs tooling before restricted ACL provisioning, and rejects `rehearsal: true` until Task 13. Protected artifacts contain `final-results` and nonsecret workflow cleanup records, not database backups or credential-bearing setup exports.

The focused `Complete-BugFixLifecycle.ps1` / `Complete-BCBenchBugFixLifecycle` entry point uses a protected `workflow-setup.json` ownership record and the existing container/account/ACL operations. Setup's opt-in `-WorkflowEvidence` preserves that record through rollback. The finalizer handles a CLI that never launches, verifies both Docker name and immutable ID, preserves existing quarantine, and quarantines incomplete handoffs rather than guessing ownership. Hard process interruption before ownership can be recorded requires manual quarantine review.

The execution handoff is separate from setup readiness: setup creates `not_started`, the workflow consumes that launch permission before invoking the CLI, and the CLI/lifecycle record their ownership before activity. Only verified contained-process, managed-client, and agent-session shutdown records `shutdown_verified`. Exclusive create-new transition locks and a terminal cleanup claim prevent launch/cleanup races; an interrupted transition or execution retains resources, disables the owned identity, and quarantines instead of treating setup readiness as shutdown proof.

Workflow cleanup runs inside the existing contained-process runner with a 180-second total worker budget (plus its bounded 30-second startup and 10-second shutdown allowances), inside a five-minute workflow step. The owned identity is disabled before container calls. A durable sibling `*.cleanup-pending.quarantine.json` is created before launching the worker and removed only after verified successful termination; timeout or supervisor cancellation retains it and blocks retries. Store-packaged WindowsApps PowerShell is rejected before provisioning because package activation can escape descendant containment; the runner must provide native PowerShell 7. No local runtime installation is performed by this change.

If runtime rejection or an interrupted pending attempt prevents the cleanup worker from securing an already-acquired identity, the supervisor reads and validates the protected setup ownership record for diagnostic purposes only. Failure evidence explicitly records identity security as unverified, warns that the account may remain enabled, and requires manual containment. It never claims disablement from setup metadata, targets a mismatched account, or runs disallowed PowerShell as a fallback; existing quarantine and pending-attempt evidence remain intact.

The cleanup child receives only an explicit Windows/profile/module-path environment allowlist. BC, lifecycle, model-provider, GitHub, Azure, and ADO credentials are not forwarded or serialized into either contained-process request JSON. The supervisor's own environment is unchanged.

The official publication and exact-test adapters pass the evaluator BC password through their PowerShell child's environment, not through the actual `-Command` argument. The existing shared templates support that channel without changing legacy template defaults. Success, nonzero exit, timeout, and launch-error regressions inspect the actual subprocess requests and evidence, rather than relying on saved-command redaction.

The exact compiler/symbol root returned by setup is included in `ToolRoots` as well as owned cleanup roots. It therefore participates in the existing read/execute grant, explicit write/delete denial, restricted-account access probes, exact CLI ACL metadata, and ownership-marker-checked cleanup.

The shared summary now selects only `evaluation-results-*`; CI's mock artifact name is updated to that prefix to preserve the existing caller. Normal Copilot/Claude workflows and the legacy setup action remain unchanged. Real container, restricted-tooling, and paid-agent canaries remain pending on a production runner; local tests do not establish those outcomes.

Production result artifacts have stable run-and-entry names with explicit overwrite on rerun, so merged downloads contain one JSONL target per entry and retain entries not rerun. Protected evidence and quarantine artifacts remain attempt-specific and are excluded from result downloads.

**Files:**
- Create: `.github\actions\setup-bugfix-lifecycle\action.yml`
- Create: `.github\workflows\bugfix-production-evaluation.yml`
- Modify: `.github\workflows\summarize-results.yml`
- Create: `tests\test_bugfix_lifecycle_workflow.py`
- Create: `scripts\Complete-BugFixLifecycle.ps1`
- Modify: `scripts\Setup-BugFixLifecycle.ps1`, `scripts\BugFixLifecycle.psm1`
- Modify: `tests\test_bugfix_lifecycle_powershell.py`, `.github\workflows\CI.yml`

- [ ] **Step 1: Write failing workflow structure tests**

Create `tests\test_bugfix_lifecycle_workflow.py` using `yaml.safe_load()` and assert:

- workflow dispatch has `agent`, `model`, `test-run`, `al-mcp`, `al-lsp`, `bc-mcp`, and `rehearsal` inputs;
- category is fixed to bug-fix;
- matrix entries come from `get-entries.yml`;
- setup uses `.github/actions/setup-bugfix-lifecycle`;
- run step invokes `uv run bcbench bugfix-lifecycle`;
- result upload includes JSONL and evidence;
- cleanup has `if: always()`;
- summary uses `skip-leaderboard: true` during opt-in rollout.

- [ ] **Step 2: Run workflow tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_workflow.py -v
```

Expected: file-not-found failures.

- [ ] **Step 3: Create the setup composite action**

The action must:

- install BcContainerHelper `6.1.18`;
- perform Azure OIDC login for the internal repository;
- resolve the entry BC version;
- cache artifacts;
- call `Setup-BugFixLifecycle.ps1`;
- expose all lifecycle path, container, agent identity, and .NET outputs;
- mask evaluator, agent OS, and agent BC passwords.

Do not modify `.github\actions\setup-bc-container-repo`; keep the production experiment isolated.

- [ ] **Step 4: Create the opt-in workflow**

The workflow must:

- accept `agent: copilot|claude`;
- validate that the selected model belongs to the selected harness;
- call `get-entries.yml` with `category: bug-fix`;
- run on `GitHub-BCBench`;
- use `max-parallel: 4` during canary rollout;
- install Python, Node, AL tooling, and both harness installers;
- invoke the matching lifecycle command with explicit roots and restricted credentials;
- upload `${EVALUATION_RESULTS_DIR}\**\*.jsonl`;
- upload protected evidence even on failure;
- run cleanup verification in an `always()` step;
- upload `quarantine.json` and fail the job when quarantine exists;
- call `summarize-results.yml` with `skip-leaderboard: true` and `production: true`.

- [ ] **Step 5: Allow separate evidence artifacts in summary workflow**

Add a `production: boolean = false` workflow-call input. Pass it to the `category bceval-config` command as `${{ inputs.production && '--production' || '' }}`. Keep result download scoped to the existing evaluation-result artifacts so evidence files cannot be mistaken for results.

- [ ] **Step 6: Run workflow tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_workflow.py tests\test_cli_commands.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add .github\actions\setup-bugfix-lifecycle\action.yml .github\workflows\bugfix-production-evaluation.yml .github\workflows\summarize-results.yml tests\test_bugfix_lifecycle_workflow.py
git commit -m "Add opt-in bug-fix production workflow" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 13: Add Checkpoint Rehearsal and Fault Injection

**Partial implementation; Task 13 is not complete.** The test-evidence portion now
shares `require_test_evidence` with production test execution and
`classify_phase_error` with production phases. The rehearsal support helper alters
real evidence files for missing JUnit, duplicate discovery, and duplicate
execution, and refuses already-invalid evidence. The additional
`DuplicateExecution` and `ServiceRestartFailure` fault names follow the approved
design; declaring them does not implement the remaining fault adapters.

**Unresolved prerequisite:** define a collision-safe AL fixture allocation and
prove its install/schema/data mutations are confined to that invocation. No
rehearsal AL fixture or reserved object-ID range was found in the repository.
The existing publisher uses `ForceSync`; this partial change does not guess an
object-ID range or execute schema mutations. The controller must resolve the
fixture allocation/preflight before wiring the real adapter.

**Remaining coherent follow-on:** implement the owned AL fixture and probe,
reuse official baseline publication plus `CheckpointManager` for the restore
loop, implement remaining adapter faults and owned cleanup, extend the durable
worker handoff, and then add the script and workflow/canary gates together.
The workflow still rejects rehearsal requests, and no Task 13 checklist item is
claimed complete. No real restore cycles, native cleanup, Docker services, or
paid agents were run by this partial implementation.

**Files:**
- Create: `scripts\Test-BugFixLifecycleCheckpoint.ps1`
- Modify: `.github\workflows\bugfix-production-evaluation.yml`
- Create: `tests\test_bugfix_lifecycle_rehearsal.py`

- [ ] **Step 1: Write rehearsal-script contract tests**

Create `tests\test_bugfix_lifecycle_rehearsal.py` that verifies the script accepts:

- `ContainerName`
- `CheckpointPath`
- `Iterations`
- `Fault`

and validates allowed faults:

- `None`
- `CorruptBackup`
- `HashMismatch`
- `ReadinessFailure`
- `UnexpectedApp`
- `MissingJUnit`
- `DuplicateDiscovery`
- `CleanupFailure`

- [ ] **Step 2: Run the contract tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_rehearsal.py -v
```

Expected: script not found.

- [ ] **Step 3: Implement restore rehearsal**

The script must:

1. capture `S0`;
2. mutate app inventory, schema, and a dedicated test-data record;
3. restore `S0`;
4. verify container ID, database topology, app inventory, data, authentication, company, endpoint, and test discovery;
5. repeat for `Iterations`;
6. emit one JSON record per iteration;
7. exit non-zero on the first mismatch.

Default `Iterations` to 10 for the dedicated rehearsal job and 1 for ordinary canary entries.

- [ ] **Step 4: Implement explicit fault injection**

Each `Fault` value must alter one controlled evaluator input and assert the resulting status:

- backup corruption and hash mismatch produce checkpoint infrastructure errors;
- readiness failure prevents tests from running;
- unexpected app fails inventory verification;
- missing JUnit and duplicate discovery produce test infrastructure errors;
- cleanup failure creates quarantine evidence.

The script must restore or remove only its own named resources in `finally`.

- [ ] **Step 5: Add a manual rehearsal job**

Add a workflow input `rehearsal: boolean`. When true, run the checkpoint rehearsal for the two entries returned by `get-entries.yml` with `test-run: true` before live agent evaluation. Do not update the leaderboard.

- [ ] **Step 6: Run contract and Python tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_rehearsal.py tests\test_bugfix_lifecycle_checkpoint.py tests\test_bugfix_lifecycle_phases.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```powershell
git add scripts\Test-BugFixLifecycleCheckpoint.ps1 .github\workflows\bugfix-production-evaluation.yml tests\test_bugfix_lifecycle_rehearsal.py
git commit -m "Add bug-fix checkpoint rehearsal" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 14: Document, Validate, and Prepare Promotion

**Files:**
- Modify: `docs\bug-fix.md`
- Modify: `README.md`
- Modify: `docs\superpowers\specs\2026-09-16-bugfix-single-container-production-lifecycle-design.md` only if implementation reveals an approved design correction

- [ ] **Step 1: Document the opt-in command and metrics**

Update `docs\bug-fix.md` with:

- opt-in workflow name;
- lifecycle command examples for Copilot, Claude, and replay;
- `GeneratedTestValidity`, `GeneratedPairTransition`, `FixBuild`, `FixQuality`, and `Resolution`;
- success rate versus coverage;
- timeout-forces-resolution-failure rule;
- runtime isolation value;
- evidence artifact contents;
- warning not to aggregate different isolation modes.

- [ ] **Step 2: Add operator prerequisites**

Document in `README.md`:

- Windows self-hosted runner with local-user administration;
- Docker/BcContainerHelper access for evaluator identity;
- PowerShell 7;
- protected storage and mounted staging requirements;
- quarantine marker location;
- evaluator versus agent credential variables.

- [ ] **Step 3: Run all targeted tests**

Run:

```powershell
uv run pytest tests\test_bugfix_lifecycle_results.py tests\test_bugfix_lifecycle_summary.py tests\test_submission_freeze.py tests\test_bugfix_output.py tests\test_bugfix_lifecycle_evidence.py tests\test_bugfix_lifecycle_workspace.py tests\test_contained_process.py tests\test_agent_env.py tests\test_copilot_cli.py tests\test_claude_agent.py tests\test_bugfix_lifecycle_powershell.py tests\test_bugfix_lifecycle_checkpoint.py tests\test_bugfix_lifecycle_phases.py tests\test_bugfix_production_lifecycle.py tests\test_cli_commands.py tests\test_bugfix_lifecycle_workflow.py tests\test_bugfix_lifecycle_rehearsal.py -v
```

Expected: all targeted tests pass.

- [ ] **Step 4: Run formatting and linting**

Run:

```powershell
uv run ruff format
uv run ruff check --fix
uv run ruff format --check
uv run ruff check
```

Expected: no remaining formatting or lint errors.

- [ ] **Step 5: Run the full non-e2e suite**

Run:

```powershell
uv run pytest
```

Expected: all non-e2e tests pass.

- [ ] **Step 6: Run a deterministic replay canary**

On a production runner, replay at least these frozen submission classes:

1. full success;
2. invalid generated test with valid fix;
3. generated build failure;
4. wrong red outcome;
5. timeout-marked patch.

For every replay, verify phase evidence, legacy projection, metric coverage, package inventory, container deletion, and absence of quarantine.

- [ ] **Step 7: Run checkpoint rehearsal**

Run:

```powershell
.\scripts\Test-BugFixLifecycleCheckpoint.ps1 -ContainerName $env:BC_CONTAINER_NAME -CheckpointPath $env:BCBENCH_LIFECYCLE_CHECKPOINTS -Iterations 10 -Fault None
```

Expected: ten consecutive successful restore records and exit code 0.

- [ ] **Step 8: Run fault-injection cases**

Run each supported fault once. Expected: the evaluator emits the specified infrastructure/invalid status, does not run unsafe tests, removes the container, and creates quarantine only for cleanup failure.

- [ ] **Step 9: Run a five-entry live canary**

Dispatch `.github\workflows\bugfix-production-evaluation.yml` with `test-run: true`, inspect every evidence artifact, and confirm:

- every phase starts from the intended checkpoint;
- package inventories match;
- every requested test is discovered and executed once;
- independent fix evaluation runs after invalid generated tests;
- every container is absent after completion;
- no unexplained infrastructure classification occurs.

- [ ] **Step 10: Commit documentation**

```powershell
git add docs\bug-fix.md README.md
git commit -m "Document bug-fix production evaluation" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 11: Request code review**

Invoke the `requesting-code-review` skill. Address only findings tied to this lifecycle, rerun the smallest affected tests, then rerun `uv run pytest`.

## Promotion Checklist

Do not make the production lifecycle the default until all are true:

- [ ] Unit, targeted, lint, and full non-e2e suites pass.
- [ ] Contained-process timeout leaves no child or grandchild processes.
- [ ] Restricted agent identity cannot read protected storage or invoke Docker.
- [ ] Ten consecutive checkpoint restores pass across two representative entries.
- [ ] Every injected fault maps to the expected status.
- [ ] Deterministic replay validates all five submission classes.
- [ ] Five-entry live canary has complete evidence and verified cleanup.
- [ ] Bug-fix summaries report success, determined failure, unknown, scheduled, rate, and coverage for all five metrics.
- [ ] Package-normalized and database-checkpointed runs have different combination keys.
- [ ] The opt-in workflow keeps leaderboard updates disabled.

After one complete scheduled production evaluation cycle with no unexplained infrastructure failures, cleanup failures, missing evidence, or quarantine events:

1. Switch normal bug-fix Copilot and Claude workflow branches to `bcbench bugfix-lifecycle`.
2. Enable the five production bc-eval evaluators by default for bug-fix.
3. Enable leaderboard updates for the checkpointed isolation key.
4. Remove the old package-normalized bug-fix runtime path in a separate cleanup change.
