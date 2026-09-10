# Bug-fix Evaluator Package Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bug-fix evaluation normalize every touched AL project, discover generated test projects by nearest `app.json`, and prove exact fail-to-pass execution before accepting a fix.

**Architecture:** Freeze and analyze the agent patch before cleanup, then drive three explicit package-normalized gates from `BugFixPipeline`. Add a shared exact test runner that collects BCContainerHelper discovery data and JUnit evidence, while preserving test-generation's existing "at least one pre-fix failure" rule through an explicit expectation enum.

**Tech Stack:** Python 3.13, Pydantic, `unidiff`, pytest, PowerShell 7, BCContainerHelper 6.1.x, AL/Business Central containers, `uv`, Ruff.

---

## File Structure

### New files

- `src\bcbench\evaluate\bugfix_output.py` - Freeze, classify, and validate generated bug-fix output.
- `src\bcbench\operations\test_execution.py` - Test identity, outcome, expectation, evidence parsing, and exact-result validation.
- `tests\test_bugfix_output.py` - Generated patch/project ownership tests.
- `tests\test_test_execution.py` - Discovery/JUnit evidence and expectation tests.

### Modified files

- `src\bcbench\exceptions.py` - Add project/evidence errors and attach structured summaries to test failures.
- `src\bcbench\operations\project_operations.py` - Resolve nearest-`app.json` project ownership and deterministic project ordering.
- `src\bcbench\operations\bc_operations.py` - Collect exact test evidence and return `TestRunSummary`.
- `src\bcbench\operations\__init__.py` - Export the new project and test execution APIs.
- `scripts\AppUtils.psm1` - Write per-codeunit discovery JSON and JUnit files.
- `src\bcbench\evaluate\bugfix.py` - Implement the three package-normalized gates.
- `src\bcbench\evaluate\testgeneration.py` - Pass the repository path and preserve current pre-fix expectation semantics.
- `src\bcbench\results\base.py` - Persist evaluator commit provenance.
- `src\bcbench\results\bugfix.py` - Persist phase counts and runtime isolation.
- `src\bcbench\results\summary.py` - Carry evaluator commit SHA into run summaries.
- `src\bcbench\results\bceval_export.py` - Export evaluator SHA and runtime isolation metadata.
- `tests\conftest.py` - Build bug-fix result fixtures with the new fields.
- `tests\test_project_categorization.py` - Cover nearest-project resolution and ordering.
- `tests\test_ps_templates.py` - Cover evidence-directory PowerShell generation.
- `tests\test_bugfix_pipeline.py` - Cover exact normalization and gate ordering.
- `tests\test_evaluation_factories.py` - Cover successful and failed count creation.
- `tests\test_result_hierarchy.py` - Cover metrics and display fields.
- `tests\test_result_serialization.py` - Cover JSONL persistence.
- `tests\test_result_writer.py` - Cover bceval provenance metadata.
- `tests\test_evaluation_summary.py` - Cover evaluator SHA propagation.
- `pyproject.toml` - Bump benchmark methodology version to `1.0.0`.
- `docs\bug-fix.md` - Describe package-normalized dual verification and its limitation.

## Task 1: Resolve AL Project Ownership from `app.json`

**Files:**
- Modify: `src\bcbench\exceptions.py:154-215`
- Modify: `src\bcbench\operations\project_operations.py`
- Modify: `src\bcbench\operations\__init__.py`
- Test: `tests\test_project_categorization.py`

- [ ] **Step 1: Write failing nearest-project tests**

Add these tests to `tests\test_project_categorization.py`:

```python
from pathlib import Path

import pytest

from bcbench.exceptions import ProjectDiscoveryError
from bcbench.operations.project_operations import find_project_path, order_project_paths


def _create_project(repo_path: Path, relative_path: str) -> Path:
    project_path = repo_path / relative_path
    project_path.mkdir(parents=True)
    (project_path / "app.json").write_text("{}", encoding="utf-8")
    return project_path


def test_find_project_path_uses_nearest_app_json(tmp_path):
    repo_path = tmp_path / "repo"
    project_path = _create_project(repo_path, "App/Layers/W1/Tests/SCM-Manufacturing")
    test_file = project_path / "ProductionOrder.Codeunit.al"
    test_file.write_text("codeunit 137310 Tests {}", encoding="utf-8")

    assert find_project_path(repo_path, "App/Layers/W1/Tests/SCM-Manufacturing/ProductionOrder.Codeunit.al") == str(
        project_path.relative_to(repo_path)
    )


def test_find_project_path_prefers_nested_bcapps_test_project(tmp_path):
    repo_path = tmp_path / "repo"
    _create_project(repo_path, "src/MyApp")
    test_project = _create_project(repo_path, "src/MyApp/test")
    test_file = test_project / "Regression.Codeunit.al"
    test_file.write_text("codeunit 50100 Tests {}", encoding="utf-8")

    assert find_project_path(repo_path, "src/MyApp/test/Regression.Codeunit.al") == str(test_project.relative_to(repo_path))


def test_find_project_path_rejects_file_without_app_json(tmp_path):
    repo_path = tmp_path / "repo"
    source_file = repo_path / "App/Unknown/Thing.al"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("table 50100 Thing {}", encoding="utf-8")

    with pytest.raises(ProjectDiscoveryError, match="No owning app.json"):
        find_project_path(repo_path, "App/Unknown/Thing.al")


def test_find_project_path_rejects_repository_escape(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    with pytest.raises(ProjectDiscoveryError, match="outside repository"):
        find_project_path(repo_path, "../outside.al")


def test_order_project_paths_prefers_dataset_order_then_sorts_new_paths():
    declared = ["App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\SCM"]
    discovered = [
        "App/Layers/W1/Tests/SCM-Manufacturing",
        "App/Layers/W1/BaseApp",
        "App/Layers/W1/Tests/Assembly",
    ]

    assert order_project_paths(declared, discovered) == [
        "App/Layers/W1/BaseApp",
        "App/Layers/W1/Tests/Assembly",
        "App/Layers/W1/Tests/SCM-Manufacturing",
    ]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
uv run pytest tests\test_project_categorization.py -k "find_project_path or order_project_paths" -v
```

Expected: collection errors because `ProjectDiscoveryError`, `find_project_path`, and `order_project_paths` do not exist.

- [ ] **Step 3: Add the project discovery error**

Add to `src\bcbench\exceptions.py` after `BuildTimeoutExpired`:

```python
class ProjectDiscoveryError(BCBenchError):
    """A changed AL file cannot be associated with a valid project."""
```

- [ ] **Step 4: Implement nearest-`app.json` ownership and ordering**

Replace the top of `src\bcbench\operations\project_operations.py` and add the new public helpers:

```python
"""Project path categorization and management operations."""

from collections.abc import Iterable
from pathlib import Path

from bcbench.config import get_config
from bcbench.exceptions import ProjectDiscoveryError
from bcbench.logger import get_logger

logger = get_logger(__name__)
_config = get_config()


def _canonical_project_path(project_path: str) -> str:
    return project_path.replace("\\", "/").rstrip("/").casefold()


def _is_test_project(project_path: str, test_identifiers: tuple[str, ...]) -> bool:
    project_lower = project_path.replace("\\", "/").casefold()
    return any(f"/{identifier.casefold()}" in project_lower for identifier in test_identifiers)


def is_test_project(project_path: str) -> bool:
    return _is_test_project(project_path, _config.file_patterns.test_project_identifiers)


def find_project_path(repo_path: Path, file_path: str) -> str:
    resolved_repo = repo_path.resolve()
    resolved_file = (repo_path / Path(file_path)).resolve()
    if not resolved_file.is_relative_to(resolved_repo):
        raise ProjectDiscoveryError(f"Changed file is outside repository: {file_path}")

    current = resolved_file.parent
    while current.is_relative_to(resolved_repo):
        if (current / "app.json").is_file():
            return str(current.relative_to(resolved_repo))
        if current == resolved_repo:
            break
        current = current.parent

    raise ProjectDiscoveryError(f"No owning app.json found for changed file: {file_path}")


def order_project_paths(preferred_paths: Iterable[str], discovered_paths: Iterable[str]) -> list[str]:
    discovered_by_key = {_canonical_project_path(path): path for path in discovered_paths}
    ordered = [
        discovered_by_key.pop(_canonical_project_path(path))
        for path in preferred_paths
        if _canonical_project_path(path) in discovered_by_key
    ]
    return [*ordered, *sorted(discovered_by_key.values(), key=_canonical_project_path)]
```

Update `categorize_projects()` to call `is_test_project()`. Keep `_is_test_project()` because its explicit-identifier contract is already covered by unit tests.

- [ ] **Step 5: Export the helpers**

Update `src\bcbench\operations\__init__.py`:

```python
from bcbench.operations.project_operations import categorize_projects, find_project_path, is_test_project, order_project_paths
```

Add `"find_project_path"`, `"is_test_project"`, and `"order_project_paths"` to `__all__`.

- [ ] **Step 6: Run tests and formatting**

Run:

```powershell
uv run pytest tests\test_project_categorization.py -v
uv run ruff check --fix src\bcbench\operations\project_operations.py src\bcbench\exceptions.py tests\test_project_categorization.py
uv run ruff format src\bcbench\operations\project_operations.py src\bcbench\exceptions.py tests\test_project_categorization.py
```

Expected: all project categorization tests pass; Ruff reports no remaining errors.

- [ ] **Step 7: Commit**

```powershell
git add src\bcbench\exceptions.py src\bcbench\operations\project_operations.py src\bcbench\operations\__init__.py tests\test_project_categorization.py
git commit -m "Add AL project ownership discovery" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 2: Freeze and Classify Generated Bug-fix Output

**Files:**
- Create: `src\bcbench\evaluate\bugfix_output.py`
- Create: `tests\test_bugfix_output.py`
- Modify: `src\bcbench\exceptions.py`

- [ ] **Step 1: Write failing analyzer tests**

Create `tests\test_bugfix_output.py`:

```python
from pathlib import Path

import pytest

from bcbench.evaluate.bugfix_output import analyze_generated_bugfix_output
from bcbench.exceptions import GeneratedOutputError, NoTestsExtractedError, ProjectDiscoveryError


def _create_project(repo_path: Path, relative_path: str) -> Path:
    project_path = repo_path / relative_path
    project_path.mkdir(parents=True)
    (project_path / "app.json").write_text("{}", encoding="utf-8")
    return project_path


def _two_file_patch(app_file: str, test_file: str) -> str:
    return f"""diff --git a/{app_file} b/{app_file}
index 1111111..2222222 100644
--- a/{app_file}
+++ b/{app_file}
@@ -1,3 +1,4 @@
 codeunit 50100 Product
 {{
+    procedure Fix() begin end;
 }}
diff --git a/{test_file} b/{test_file}
index 3333333..4444444 100644
--- a/{test_file}
+++ b/{test_file}
@@ -1,3 +1,7 @@
 codeunit 50101 Tests
 {{
+    [Test]
+    procedure RegressionTest()
+    begin
+    end;
 }}
"""


def test_analyzer_discovers_generated_test_project_outside_entry_paths(tmp_path):
    repo_path = tmp_path / "repo"
    app_project = _create_project(repo_path, "App/Layers/W1/BaseApp")
    test_project = _create_project(repo_path, "App/Layers/W1/Tests/SCM-Manufacturing")
    app_file = app_project / "Product.Codeunit.al"
    test_file = test_project / "Tests.Codeunit.al"
    app_file.write_text("codeunit 50100 Product {}", encoding="utf-8")
    test_file.write_text(
        'codeunit 50101 "Tests"\n{\n    [Test]\n    procedure RegressionTest()\n    begin\n    end;\n}\n',
        encoding="utf-8",
    )

    output = analyze_generated_bugfix_output(
        repo_path,
        _two_file_patch(
            "App/Layers/W1/BaseApp/Product.Codeunit.al",
            "App/Layers/W1/Tests/SCM-Manufacturing/Tests.Codeunit.al",
        ),
    )

    assert output.app_projects == (str(app_project.relative_to(repo_path)),)
    assert output.test_projects == (str(test_project.relative_to(repo_path)),)
    assert output.tests[0].codeunitID == 50101
    assert output.tests[0].functionName == {"RegressionTest"}
    assert "procedure Fix" in output.fix_patch
    assert "procedure RegressionTest" in output.test_patch


def test_analyzer_rejects_test_only_patch(tmp_path):
    repo_path = tmp_path / "repo"
    test_project = _create_project(repo_path, "App/Layers/W1/Tests/SCM")
    test_file = test_project / "Tests.Codeunit.al"
    test_file.write_text(
        'codeunit 50101 "Tests"\n{\n    [Test]\n    procedure RegressionTest()\n    begin\n    end;\n}\n',
        encoding="utf-8",
    )
    patch = """diff --git a/App/Layers/W1/Tests/SCM/Tests.Codeunit.al b/App/Layers/W1/Tests/SCM/Tests.Codeunit.al
index 3333333..4444444 100644
--- a/App/Layers/W1/Tests/SCM/Tests.Codeunit.al
+++ b/App/Layers/W1/Tests/SCM/Tests.Codeunit.al
@@ -1,3 +1,7 @@
 codeunit 50101 Tests
 {
+    [Test]
+    procedure RegressionTest()
+    begin
+    end;
 }
"""

    with pytest.raises(GeneratedOutputError, match="no product-code fix"):
        analyze_generated_bugfix_output(repo_path, patch)


def test_analyzer_rejects_fix_without_new_test(tmp_path):
    repo_path = tmp_path / "repo"
    app_project = _create_project(repo_path, "App/Layers/W1/BaseApp")
    app_file = app_project / "Product.Codeunit.al"
    app_file.write_text("codeunit 50100 Product {}", encoding="utf-8")
    patch = """diff --git a/App/Layers/W1/BaseApp/Product.Codeunit.al b/App/Layers/W1/BaseApp/Product.Codeunit.al
index 1111111..2222222 100644
--- a/App/Layers/W1/BaseApp/Product.Codeunit.al
+++ b/App/Layers/W1/BaseApp/Product.Codeunit.al
@@ -1 +1,2 @@
 codeunit 50100 Product {}
+procedure Fix() begin end;
"""

    with pytest.raises(NoTestsExtractedError):
        analyze_generated_bugfix_output(repo_path, patch)
```

- [ ] **Step 2: Run tests and verify they fail**

```powershell
uv run pytest tests\test_bugfix_output.py -v
```

Expected: import errors because the module and `GeneratedOutputError` do not exist.

- [ ] **Step 3: Add the generated-output error**

Add to `src\bcbench\exceptions.py`:

```python
class GeneratedOutputError(BCBenchError):
    """Generated bug-fix output violates the required patch shape."""
```

- [ ] **Step 4: Implement the analyzer**

Create `src\bcbench\evaluate\bugfix_output.py`:

```python
from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet

from bcbench.dataset import TestEntry
from bcbench.exceptions import GeneratedOutputError
from bcbench.operations.project_operations import find_project_path, is_test_project
from bcbench.operations.test_operations import extract_tests_from_patch


@dataclass(frozen=True)
class GeneratedBugFixOutput:
    full_patch: str
    fix_patch: str
    test_patch: str
    app_projects: tuple[str, ...]
    test_projects: tuple[str, ...]
    tests: tuple[TestEntry, ...]


def analyze_generated_bugfix_output(repo_path: Path, generated_patch: str) -> GeneratedBugFixOutput:
    fix_files = []
    test_files = []
    app_projects: set[str] = set()
    test_projects: set[str] = set()

    for patched_file in PatchSet(generated_patch):
        project_path = find_project_path(repo_path, patched_file.path)
        if is_test_project(project_path):
            test_files.append(patched_file)
            test_projects.add(project_path)
        else:
            fix_files.append(patched_file)
            app_projects.add(project_path)

    fix_patch = "".join(str(patched_file) for patched_file in fix_files)
    test_patch = "".join(str(patched_file) for patched_file in test_files)
    if not fix_patch.strip():
        raise GeneratedOutputError("Agent produced tests but no product-code fix.")

    file_contents = {
        patched_file.path: (repo_path / Path(patched_file.path)).read_text(encoding="utf-8")
        for patched_file in test_files
        if (repo_path / Path(patched_file.path)).is_file()
    }
    tests = tuple(extract_tests_from_patch(test_patch, file_contents))

    return GeneratedBugFixOutput(
        full_patch=generated_patch,
        fix_patch=fix_patch,
        test_patch=test_patch,
        app_projects=tuple(sorted(app_projects, key=str.casefold)),
        test_projects=tuple(sorted(test_projects, key=str.casefold)),
        tests=tests,
    )
```

- [ ] **Step 5: Add missing-project coverage**

Extend `tests\test_bugfix_output.py` with:

```python
def test_analyzer_rejects_changed_file_without_project(tmp_path):
    repo_path = tmp_path / "repo"
    changed_file = repo_path / "Unknown/Product.al"
    changed_file.parent.mkdir(parents=True)
    changed_file.write_text("table 50100 Product {}", encoding="utf-8")
    patch = """diff --git a/Unknown/Product.al b/Unknown/Product.al
index 1111111..2222222 100644
--- a/Unknown/Product.al
+++ b/Unknown/Product.al
@@ -1 +1,2 @@
 table 50100 Product {}
+procedure Fix() begin end;
"""

    with pytest.raises(ProjectDiscoveryError, match="No owning app.json"):
        analyze_generated_bugfix_output(repo_path, patch)
```

- [ ] **Step 6: Run tests and formatting**

```powershell
uv run pytest tests\test_bugfix_output.py tests\test_extract_tests_from_patch.py -v
uv run ruff check --fix src\bcbench\evaluate\bugfix_output.py tests\test_bugfix_output.py
uv run ruff format src\bcbench\evaluate\bugfix_output.py tests\test_bugfix_output.py
```

Expected: all analyzer and extraction tests pass.

- [ ] **Step 7: Commit**

```powershell
git add src\bcbench\exceptions.py src\bcbench\evaluate\bugfix_output.py tests\test_bugfix_output.py
git commit -m "Analyze generated bug-fix output by project" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 3: Model and Validate Exact Test Evidence

**Files:**
- Create: `src\bcbench\operations\test_execution.py`
- Create: `tests\test_test_execution.py`
- Modify: `src\bcbench\exceptions.py`
- Modify: `src\bcbench\operations\__init__.py`

- [ ] **Step 1: Write failing evidence parser tests**

Create `tests\test_test_execution.py`:

```python
import json
from pathlib import Path

import pytest

from bcbench.dataset import TestEntry
from bcbench.exceptions import TestExecutionError
from bcbench.operations.test_execution import TestExpectation, load_test_run_summary


def _write_evidence(
    evidence_dir: Path,
    codeunit_id: int,
    discovered: list[str],
    outcomes: dict[str, str],
) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / f"discovery-{codeunit_id}.json").write_text(
        json.dumps({"codeunitID": codeunit_id, "functionName": discovered}),
        encoding="utf-8",
    )
    cases = "".join(
        f'<testcase name="{name}">{"<failure />" if outcome == "Fail" else "<skipped />" if outcome == "Skip" else ""}</testcase>'
        for name, outcome in outcomes.items()
    )
    (evidence_dir / f"results-{codeunit_id}.xml").write_text(
        f'<testsuites><testsuite name="{codeunit_id} Tests">{cases}</testsuite></testsuites>',
        encoding="utf-8",
    )


def test_all_fail_accepts_exact_failed_identity(tmp_path):
    entries = [TestEntry(codeunitID=137310, functionName=frozenset({"RegressionTest"}))]
    _write_evidence(tmp_path, 137310, ["RegressionTest"], {"RegressionTest": "Fail"})

    summary = load_test_run_summary(tmp_path, entries)
    summary.require(TestExpectation.ALL_FAIL)

    assert summary.requested_count == 1
    assert summary.discovered_count == 1
    assert summary.executed_count == 1


def test_all_fail_rejects_mixed_outcomes(tmp_path):
    entries = [TestEntry(codeunitID=137310, functionName=frozenset({"RegressionTest", "AlreadyPassing"}))]
    _write_evidence(
        tmp_path,
        137310,
        ["RegressionTest", "AlreadyPassing"],
        {"RegressionTest": "Fail", "AlreadyPassing": "Pass"},
    )

    with pytest.raises(TestExecutionError, match="all tests to fail"):
        load_test_run_summary(tmp_path, entries).require(TestExpectation.ALL_FAIL)


def test_empty_selection_is_rejected(tmp_path):
    with pytest.raises(TestExecutionError, match="No tests requested"):
        load_test_run_summary(tmp_path, []).require(TestExpectation.ALL_PASS)


@pytest.mark.parametrize(
    ("discovered", "outcomes", "message"),
    [
        ([], {}, "Missing discovered tests"),
        (["RegressionTest"], {}, "Missing executed tests"),
        (["RegressionTest"], {"RegressionTest": "Skip"}, "Skipped tests"),
        (
            ["RegressionTest"],
            {"RegressionTest": "Pass", "UnexpectedTest": "Pass"},
            "Unexpected executed tests",
        ),
    ],
)
def test_exact_identity_validation(tmp_path, discovered, outcomes, message):
    entries = [TestEntry(codeunitID=137310, functionName=frozenset({"RegressionTest"}))]
    _write_evidence(tmp_path, 137310, discovered, outcomes)

    with pytest.raises(TestExecutionError, match=message):
        load_test_run_summary(tmp_path, entries).require(TestExpectation.ALL_PASS)
```

- [ ] **Step 2: Run tests and verify they fail**

```powershell
uv run pytest tests\test_test_execution.py -v
```

Expected: import errors because the evidence module does not exist.

- [ ] **Step 3: Extend `TestExecutionError`**

Replace `TestExecutionError` in `src\bcbench\exceptions.py` with:

```python
class TestExecutionError(BCBenchError):
    """Test selection, execution, or outcome does not meet the gate contract."""

    def __init__(
        self,
        expectation: str,
        stderr: str = "",
        stdout: str = "",
        *,
        reason: str | None = None,
        summary: object | None = None,
    ) -> None:
        self.expectation = expectation
        self.stderr = stderr
        self.stdout = stdout
        self.summary = summary
        self.errors = _extract_test_errors(stdout)
        message = reason or f"Test result did not meet expectation (expected: {expectation})"
        if self.errors:
            message += f"\n{self.errors}"
        super().__init__(message)
```

- [ ] **Step 4: Implement evidence models and parsing**

Create `src\bcbench\operations\test_execution.py`:

```python
import json
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from bcbench.dataset import TestEntry
from bcbench.exceptions import TestExecutionError


class TestExpectation(StrEnum):
    ALL_PASS = "all-pass"
    ALL_FAIL = "all-fail"
    ANY_FAIL = "any-fail"


class TestOutcome(StrEnum):
    PASS = "Pass"
    FAIL = "Fail"
    SKIP = "Skip"


@dataclass(frozen=True, order=True)
class TestIdentity:
    codeunit_id: int
    function_name: str


@dataclass(frozen=True)
class TestCaseResult:
    identity: TestIdentity
    outcome: TestOutcome


@dataclass(frozen=True)
class TestRunSummary:
    requested: tuple[TestIdentity, ...]
    discovered: tuple[TestIdentity, ...]
    results: tuple[TestCaseResult, ...]

    @property
    def executed(self) -> tuple[TestIdentity, ...]:
        return tuple(result.identity for result in self.results)

    @property
    def requested_count(self) -> int:
        return len(self.requested)

    @property
    def discovered_count(self) -> int:
        return len(self.discovered)

    @property
    def executed_count(self) -> int:
        return len(self.results)

    @classmethod
    def combine(cls, summaries: list["TestRunSummary"]) -> "TestRunSummary":
        return cls(
            requested=tuple(identity for summary in summaries for identity in summary.requested),
            discovered=tuple(identity for summary in summaries for identity in summary.discovered),
            results=tuple(result for summary in summaries for result in summary.results),
        )

    def require(self, expectation: TestExpectation) -> None:
        requested = Counter(self.requested)
        discovered = Counter(self.discovered)
        executed = Counter(self.executed)
        if not requested:
            raise TestExecutionError(expectation, reason="No tests requested", summary=self)
        if missing := requested - discovered:
            raise TestExecutionError(expectation, reason=f"Missing discovered tests: {sorted(missing.elements())}", summary=self)
        if missing := requested - executed:
            raise TestExecutionError(expectation, reason=f"Missing executed tests: {sorted(missing.elements())}", summary=self)
        if unexpected := executed - requested:
            raise TestExecutionError(expectation, reason=f"Unexpected executed tests: {sorted(unexpected.elements())}", summary=self)
        if skipped := [result.identity for result in self.results if result.outcome is TestOutcome.SKIP]:
            raise TestExecutionError(expectation, reason=f"Skipped tests: {skipped}", summary=self)

        outcomes = [result.outcome for result in self.results]
        if expectation is TestExpectation.ALL_PASS and any(outcome is not TestOutcome.PASS for outcome in outcomes):
            raise TestExecutionError(expectation, reason="Expected all tests to pass", summary=self)
        if expectation is TestExpectation.ALL_FAIL and any(outcome is not TestOutcome.FAIL for outcome in outcomes):
            raise TestExecutionError(expectation, reason="Expected all tests to fail", summary=self)
        if expectation is TestExpectation.ANY_FAIL and all(outcome is not TestOutcome.FAIL for outcome in outcomes):
            raise TestExecutionError(expectation, reason="Expected at least one test to fail", summary=self)


def _requested_identities(test_entries: list[TestEntry]) -> tuple[TestIdentity, ...]:
    return tuple(
        TestIdentity(entry.codeunitID, function_name)
        for entry in test_entries
        for function_name in sorted(entry.functionName)
    )


def load_test_run_summary(evidence_dir: Path, test_entries: list[TestEntry]) -> TestRunSummary:
    discovered: list[TestIdentity] = []
    results: list[TestCaseResult] = []
    codeunit_ids = sorted({entry.codeunitID for entry in test_entries})

    for codeunit_id in codeunit_ids:
        discovery_file = evidence_dir / f"discovery-{codeunit_id}.json"
        if discovery_file.is_file():
            payload = json.loads(discovery_file.read_text(encoding="utf-8-sig"))
            discovered.extend(TestIdentity(codeunit_id, name) for name in payload["functionName"])

        result_file = evidence_dir / f"results-{codeunit_id}.xml"
        if not result_file.is_file():
            continue
        root = ET.parse(result_file).getroot()
        for test_case in root.findall(".//testcase"):
            outcome = TestOutcome.FAIL if test_case.find("failure") is not None else TestOutcome.SKIP if test_case.find("skipped") is not None else TestOutcome.PASS
            results.append(TestCaseResult(TestIdentity(codeunit_id, test_case.attrib["name"]), outcome))

    return TestRunSummary(
        requested=_requested_identities(test_entries),
        discovered=tuple(discovered),
        results=tuple(results),
    )
```

- [ ] **Step 5: Add duplicate execution and malformed XML tests**

Add to `tests\test_test_execution.py`:

```python
def test_duplicate_execution_is_rejected(tmp_path):
    entries = [TestEntry(codeunitID=137310, functionName=frozenset({"RegressionTest"}))]
    (tmp_path / "discovery-137310.json").write_text(
        json.dumps({"codeunitID": 137310, "functionName": ["RegressionTest"]}),
        encoding="utf-8",
    )
    (tmp_path / "results-137310.xml").write_text(
        '<testsuites><testsuite><testcase name="RegressionTest" /><testcase name="RegressionTest" /></testsuite></testsuites>',
        encoding="utf-8",
    )

    with pytest.raises(TestExecutionError, match="Unexpected executed tests"):
        load_test_run_summary(tmp_path, entries).require(TestExpectation.ALL_PASS)


def test_malformed_junit_is_reported_by_parser(tmp_path):
    entries = [TestEntry(codeunitID=137310, functionName=frozenset({"RegressionTest"}))]
    (tmp_path / "discovery-137310.json").write_text(
        json.dumps({"codeunitID": 137310, "functionName": ["RegressionTest"]}),
        encoding="utf-8",
    )
    (tmp_path / "results-137310.xml").write_text("<testsuites>", encoding="utf-8")

    with pytest.raises(ET.ParseError):
        load_test_run_summary(tmp_path, entries)
```

Import `xml.etree.ElementTree as ET` in the test file.

- [ ] **Step 6: Export the test execution types**

Update `src\bcbench\operations\__init__.py`:

```python
from bcbench.operations.test_execution import TestExpectation, TestRunSummary
```

Add both names to `__all__`.

- [ ] **Step 7: Run tests and formatting**

```powershell
uv run pytest tests\test_test_execution.py tests\test_test_error_extraction.py -v
uv run ruff check --fix src\bcbench\operations\test_execution.py src\bcbench\exceptions.py tests\test_test_execution.py
uv run ruff format src\bcbench\operations\test_execution.py src\bcbench\exceptions.py tests\test_test_execution.py
```

Expected: all evidence and existing error-extraction tests pass.

- [ ] **Step 8: Commit**

```powershell
git add src\bcbench\exceptions.py src\bcbench\operations\test_execution.py src\bcbench\operations\__init__.py tests\test_test_execution.py
git commit -m "Validate exact Business Central test evidence" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 4: Collect Discovery and JUnit Evidence from BCContainerHelper

**Files:**
- Modify: `scripts\AppUtils.psm1:96-228`
- Modify: `src\bcbench\operations\bc_operations.py:83-244`
- Modify: `src\bcbench\evaluate\testgeneration.py:106-123`
- Modify: `tests\test_ps_templates.py:43-264`
- Test: `tests\test_test_execution.py`

- [ ] **Step 1: Update PowerShell template tests first**

Change the dataset script tests in `tests\test_ps_templates.py` to pass an evidence directory:

```python
script = bc_operations.build_ps_dataset_tests_script(
    container_name="bcserver",
    username="admin",
    ******,
    test_entries_json=test_entries,
    evidence_directory=Path(r"C:\repo\.bcbench-test-evidence"),
)

assert "Invoke-DatasetTests" in script
assert "-evidenceDirectory 'C:\\repo\\.bcbench-test-evidence'" in script
assert "-expectation" not in script
```

Change the `run_test_suite` subprocess fixtures to create matching discovery/JUnit files in the evidence directory obtained from the generated command before returning.

- [ ] **Step 2: Run the template tests and verify they fail**

```powershell
uv run pytest tests\test_ps_templates.py -v
```

Expected: failures because `evidence_directory` is not accepted and the generated script still passes `expectation`.

- [ ] **Step 3: Replace `Invoke-BCTest` with evidence-producing behavior**

In `scripts\AppUtils.psm1`, add a mandatory `evidenceDirectory` parameter to `Invoke-BCTest` and replace its execution body with:

```powershell
    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    [string] $combinedFunctions = $functionNames -join '|'
    [object[]] $availableCodeunits = @(
        Get-TestsFromBcContainer `
            -containerName $containerName `
            -credential $credential `
            -testCodeunitRange $codeunitID.ToString() `
            -ignoreGroups
    )
    [object] $availableCodeunit = $availableCodeunits |
        Where-Object { [int]$_.Id -eq $codeunitID } |
        Select-Object -First 1
    [string[]] $availableFunctions = if ($availableCodeunit) { @($availableCodeunit.Tests) } else { @() }
    [string[]] $discoveredFunctions = @(
        $functionNames | Where-Object { $availableFunctions -ccontains $_ }
    )

    [string] $discoveryPath = Join-Path $evidenceDirectory "discovery-$codeunitID.json"
    [PSCustomObject]@{
        codeunitID  = $codeunitID
        functionName = $discoveredFunctions
    } | ConvertTo-Json -Depth 5 | Set-Content -Path $discoveryPath -Encoding UTF8

    [string] $resultPath = Join-Path $evidenceDirectory "results-$codeunitID.xml"
    [hashtable] $testParams = @{
        containerName         = $containerName
        credential            = $credential
        returnTrueIfAllPassed = $true
        testCodeunitRange     = $codeunitID.ToString()
        testFunction          = $combinedFunctions
        detailed              = $true
        JUnitResultFileName   = $resultPath
    }

    return [bool](Run-TestsInBcContainer @testParams)
```

Keep existing logging and exception logging around this body.

- [ ] **Step 4: Simplify `Invoke-DatasetTests` to collect evidence**

Replace its `expectation` parameter with:

```powershell
        [Parameter(Mandatory = $true)]
        [string] $evidenceDirectory
```

Replace its body after the empty-input guard with:

```powershell
    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    foreach ($testEntry in $testEntries) {
        [int] $codeunitID = $testEntry.codeunitID
        [string[]] $functionNames = $testEntry.functionName
        Invoke-BCTest `
            -containerName $containerName `
            -credential $credential `
            -codeunitID $codeunitID `
            -functionNames $functionNames `
            -evidenceDirectory $evidenceDirectory | Out-Null
    }
```

Do not validate pass/fail in PowerShell. Python owns the gate rule after parsing evidence.

- [ ] **Step 5: Change the Python script builder**

Update `_DATASET_TESTS_TEMPLATE` in `src\bcbench\operations\bc_operations.py`:

```python
_DATASET_TESTS_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$app_utils_path' -Force
$$ErrorActionPreference = 'Stop'

$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)
$$testEntries = '$test_entries_json' | ConvertFrom-Json

Invoke-DatasetTests -containerName '$container_name' -credential $$credential -testEntries $$testEntries -evidenceDirectory '$evidence_directory'
""".strip()
)
```

Change `build_ps_dataset_tests_script()` to accept `evidence_directory: Path` and substitute its escaped value.

- [ ] **Step 6: Make `run_test_suite` return exact evidence**

Add a normalization helper and replace `run_test_suite()` in `src\bcbench\operations\bc_operations.py`:

```python
def _normalize_test_entries(test_entries: list[TestEntry]) -> list[TestEntry]:
    functions_by_codeunit: dict[int, set[str]] = {}
    for entry in test_entries:
        functions_by_codeunit.setdefault(entry.codeunitID, set()).update(entry.functionName)
    return [
        TestEntry(codeunitID=codeunit_id, functionName=frozenset(function_names))
        for codeunit_id, function_names in sorted(functions_by_codeunit.items())
    ]


def run_test_suite(
    test_entries: list[TestEntry],
    expectation: TestExpectation,
    container: ContainerConfig,
    repo_path: Path,
) -> TestRunSummary:
    normalized_entries = _normalize_test_entries(test_entries)
    test_entries_json = TypeAdapter(list[TestEntry]).dump_json(normalized_entries).decode()

    with tempfile.TemporaryDirectory(prefix=".bcbench-test-evidence-", dir=repo_path) as evidence_directory:
        evidence_path = Path(evidence_directory)
        ps_script = build_ps_dataset_tests_script(
            container_name=container.name,
            username=container.username,
            ******,
            test_entries_json=test_entries_json,
            evidence_directory=evidence_path,
        )
        try:
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                cwd=repo_path,
                capture_output=True,
                check=False,
                text=True,
                timeout=_config.timeout.test_execution,
            )
        except subprocess.TimeoutExpired:
            raise TestExecutionTimeoutExpired(test_entries_json, _config.timeout.test_execution) from None

        try:
            summary = load_test_run_summary(evidence_path, normalized_entries)
        except (OSError, ValueError, ET.ParseError) as error:
            raise TestExecutionError(
                expectation,
                stdout=result.stdout,
                stderr=result.stderr,
                reason=f"Invalid test evidence: {error}",
            ) from error

        if result.returncode != 0:
            raise TestExecutionError(
                expectation,
                stdout=result.stdout,
                stderr=result.stderr,
                reason="Business Central test execution failed before evidence validation",
                summary=summary,
            )

        summary.require(expectation)
        return summary
```

Add imports for `tempfile`, `xml.etree.ElementTree as ET`, `TestExpectation`, `TestRunSummary`, and `load_test_run_summary`.

- [ ] **Step 7: Make hidden benchmark runs return a combined summary**

Replace `run_tests()`:

```python
def run_tests(entry: _BugFixTestGenBase, container: ContainerConfig, repo_path: Path) -> TestRunSummary:
    summaries = []
    if entry.fail_to_pass:
        summaries.append(run_test_suite(entry.fail_to_pass, TestExpectation.ALL_PASS, container, repo_path))
    if entry.pass_to_pass:
        summaries.append(run_test_suite(entry.pass_to_pass, TestExpectation.ALL_PASS, container, repo_path))
    combined = TestRunSummary.combine(summaries)
    combined.require(TestExpectation.ALL_PASS)
    return combined
```

- [ ] **Step 8: Preserve test-generation semantics**

In `src\bcbench\evaluate\testgeneration.py`, change only the calls:

```python
run_test_suite(generated_tests, TestExpectation.ANY_FAIL, container, context.repo_path)
```

and:

```python
run_test_suite(generated_tests, TestExpectation.ALL_PASS, container, context.repo_path)
```

Import `TestExpectation`. Update its exception classification:

```python
if e.expectation is TestExpectation.ANY_FAIL:
    result = TestGenerationResult.create_pre_patch_failure(
        context,
        generated_patch,
        "Generated tests passed pre-patch\n" + str(e),
    )
else:
    result = TestGenerationResult.create_post_patch_failure(
        context,
        generated_patch,
        "Generated tests failed post-patch\n" + str(e),
    )
```

This keeps test-generation's current rule: at least one generated test must fail before the gold patch.

- [ ] **Step 9: Run focused tests**

```powershell
uv run pytest tests\test_ps_templates.py tests\test_test_execution.py tests\test_testgeneration_validation.py -v
uv run ruff check --fix src\bcbench\operations\bc_operations.py src\bcbench\evaluate\testgeneration.py tests\test_ps_templates.py tests\test_test_execution.py
uv run ruff format src\bcbench\operations\bc_operations.py src\bcbench\evaluate\testgeneration.py tests\test_ps_templates.py tests\test_test_execution.py
```

Expected: all tests pass and generated PowerShell contains evidence paths rather than expectation logic.

- [ ] **Step 10: Commit**

```powershell
git add scripts\AppUtils.psm1 src\bcbench\operations\bc_operations.py src\bcbench\evaluate\testgeneration.py tests\test_ps_templates.py tests\test_test_execution.py
git commit -m "Collect exact Business Central test evidence" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 5: Persist Verification Counts and Evaluator Provenance

**Files:**
- Modify: `src\bcbench\results\base.py`
- Modify: `src\bcbench\results\bugfix.py`
- Modify: `src\bcbench\results\summary.py`
- Modify: `src\bcbench\results\bceval_export.py`
- Modify: `tests\conftest.py`
- Modify: `tests\test_evaluation_factories.py`
- Modify: `tests\test_result_hierarchy.py`
- Modify: `tests\test_result_serialization.py`
- Modify: `tests\test_result_writer.py`
- Modify: `tests\test_evaluation_summary.py`

- [ ] **Step 1: Write failing result-count tests**

Add to `tests\test_evaluation_factories.py`:

```python
from bcbench.results.bugfix import PhaseCounts


def test_create_success_result_persists_phase_counts(sample_evaluation_context):
    counts = PhaseCounts(requested=1, discovered=1, executed=1)
    result = BugFixResult.create_success(
        sample_evaluation_context,
        "test_patch",
        pre_fix=counts,
        post_fix=counts,
        benchmark=PhaseCounts(requested=2, discovered=2, executed=2),
    )

    assert result.generated_test_requested_count == 1
    assert result.generated_test_pre_patch_discovered_count == 1
    assert result.generated_test_pre_patch_executed_count == 1
    assert result.generated_test_post_patch_discovered_count == 1
    assert result.generated_test_post_patch_executed_count == 1
    assert result.benchmark_test_requested_count == 2
    assert result.benchmark_test_discovered_count == 2
    assert result.benchmark_test_executed_count == 2
    assert result.runtime_isolation == "package-normalized"
```

Add these assertions to the existing result tests:

```python
assert result.category_metrics["generated_test_pre_patch_executed_count"] == 1
assert result.category_metrics["generated_test_post_patch_executed_count"] == 1
assert result.category_metrics["benchmark_test_executed_count"] == 2
assert result.display_row["Generated Test Pre-Fix Executed"] == "1/1"
assert result.display_row["Generated Test Post-Fix Executed"] == "1/1"
assert result.display_row["Benchmark Tests Executed"] == "2/2"
```

- [ ] **Step 2: Write failing provenance tests**

Add to `tests\test_result_serialization.py`:

```python
def test_result_records_evaluator_commit_sha(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    context = create_evaluation_context(tmp_path)
    counts = PhaseCounts(requested=1, discovered=1, executed=1)
    result = BugFixResult.create_success(
        context,
        "test patch",
        pre_fix=counts,
        post_fix=counts,
        benchmark=counts,
    )
    result.save(tmp_path, "result.jsonl")

    data = json.loads((tmp_path / "result.jsonl").read_text(encoding="utf-8"))
    assert data["evaluator_commit_sha"] == "a" * 40
```

Add to `tests\test_result_writer.py`:

```python
def test_bceval_metadata_includes_evaluator_commit_and_runtime_isolation(
    tmp_path,
    sample_dataset_file,
    problem_statement_dir,
    monkeypatch,
):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    result = create_bugfix_result(metrics=AgentMetrics(execution_time=1.0))
    result.evaluator_commit_sha = "a" * 40

    with (
        patch.object(_BugFixTestGenBase, "problem_statement_dir", property(lambda self: problem_statement_dir)),
        patch.object(EvaluationCategory, "dataset_path", new_callable=PropertyMock, return_value=sample_dataset_file),
    ):
        write_bceval_results(
            results=[result],
            out_dir=output_dir,
            run_id="run_provenance",
            output_filename="results.jsonl",
            category=EvaluationCategory.BUG_FIX,
        )

    data = json.loads((output_dir / "results.jsonl").read_text(encoding="utf-8"))
    assert data["metadata"]["evaluator_commit_sha"] == "a" * 40
    assert data["metadata"]["runtime_isolation"] == "package-normalized"
```

Add to `tests\test_evaluation_summary.py`:

```python
def test_summary_carries_evaluator_commit_sha():
    result = create_bugfix_result()
    result.evaluator_commit_sha = "a" * 40

    summary = EvaluationResultSummary.from_results([result], "run-id")

    assert summary.evaluator_commit_sha == "a" * 40
```

- [ ] **Step 3: Run tests and verify they fail**

```powershell
uv run pytest tests\test_evaluation_factories.py tests\test_result_hierarchy.py tests\test_result_serialization.py tests\test_result_writer.py tests\test_evaluation_summary.py -v
```

Expected: failures for missing count, isolation, and evaluator SHA fields.

- [ ] **Step 4: Add evaluator commit SHA to base results**

In `src\bcbench\results\base.py`, import `os`, then add:

```python
evaluator_commit_sha: str | None = None
```

Add this field to `_base_fields()`:

```python
"evaluator_commit_sha": os.environ.get("GITHUB_SHA"),
```

This records new official results without assigning the current commit to historical JSON that lacks the field.

Change the base `export_metadata` property:

```python
return {"evaluator_commit_sha": self.evaluator_commit_sha}
```

Update `JudgeScoredEvaluationResult.export_metadata` to merge `super().export_metadata` before `judge_model`.

- [ ] **Step 5: Add phase counts to `BugFixResult`**

Add above `BugFixResult`:

```python
@dataclass(frozen=True)
class PhaseCounts:
    requested: int = 0
    discovered: int = 0
    executed: int = 0
```

Add these fields:

```python
generated_test_requested_count: int = 0
generated_test_pre_patch_discovered_count: int = 0
generated_test_pre_patch_executed_count: int = 0
generated_test_post_patch_discovered_count: int = 0
generated_test_post_patch_executed_count: int = 0
benchmark_test_requested_count: int = 0
benchmark_test_discovered_count: int = 0
benchmark_test_executed_count: int = 0
runtime_isolation: str | None = None
```

Add a private helper that flattens three `PhaseCounts` values:

```python
@staticmethod
def _count_fields(pre_fix: PhaseCounts, post_fix: PhaseCounts, benchmark: PhaseCounts) -> dict[str, int]:
    return {
        "generated_test_requested_count": pre_fix.requested,
        "generated_test_pre_patch_discovered_count": pre_fix.discovered,
        "generated_test_pre_patch_executed_count": pre_fix.executed,
        "generated_test_post_patch_discovered_count": post_fix.discovered,
        "generated_test_post_patch_executed_count": post_fix.executed,
        "benchmark_test_requested_count": benchmark.requested,
        "benchmark_test_discovered_count": benchmark.discovered,
        "benchmark_test_executed_count": benchmark.executed,
    }
```

Require `pre_fix`, `post_fix`, and `benchmark` keyword arguments in `create_success()`. Add optional zero-valued `PhaseCounts` arguments to `create_verification_failure()`. Include the flattened count fields and `runtime_isolation="package-normalized"` in both constructors.

Keeping the model default as `None` prevents historical `0.11.0` result JSON from being mislabeled when it is loaded after this change.

- [ ] **Step 6: Export count metrics and readable display values**

Extend `category_metrics` with all integer count fields.

Extend `display_row` with:

```python
"Generated Test Pre-Fix Executed": f"{self.generated_test_pre_patch_executed_count}/{self.generated_test_requested_count}",
"Generated Test Post-Fix Executed": f"{self.generated_test_post_patch_executed_count}/{self.generated_test_requested_count}",
"Benchmark Tests Executed": f"{self.benchmark_test_executed_count}/{self.benchmark_test_requested_count}",
```

Override `export_metadata`:

```python
return {**super().export_metadata, "runtime_isolation": self.runtime_isolation}
```

- [ ] **Step 7: Carry evaluator SHA into summaries**

Add `evaluator_commit_sha: str | None = None` to `EvaluationResultSummary` and populate it from `first_result.evaluator_commit_sha` in `_base_fields()`.

No leaderboard combination-key change is needed because benchmark version remains the compatibility boundary; the SHA is audit metadata.

- [ ] **Step 8: Update fixtures and assertions**

Extend `create_bugfix_result()` in `tests\conftest.py` with:

```python
generated_test_requested_count: int = 1,
generated_test_pre_patch_discovered_count: int = 1,
generated_test_pre_patch_executed_count: int = 1,
generated_test_post_patch_discovered_count: int = 1,
generated_test_post_patch_executed_count: int = 1,
benchmark_test_requested_count: int = 1,
benchmark_test_discovered_count: int = 1,
benchmark_test_executed_count: int = 1,
runtime_isolation: str | None = "package-normalized",
```

Pass each value into the corresponding named `BugFixResult` field. Leave evaluator SHA unset in this direct-constructor helper unless an individual test assigns it explicitly.

Extend the exact category-metric dictionary in `tests\test_result_hierarchy.py` with all eight integer count keys. Extend `test_bugfix_verification_gates_in_jsonl` in `tests\test_result_serialization.py` with:

```python
assert data["generated_test_requested_count"] == 1
assert data["generated_test_pre_patch_discovered_count"] == 1
assert data["generated_test_pre_patch_executed_count"] == 1
assert data["generated_test_post_patch_discovered_count"] == 1
assert data["generated_test_post_patch_executed_count"] == 1
assert data["benchmark_test_requested_count"] == 1
assert data["benchmark_test_discovered_count"] == 1
assert data["benchmark_test_executed_count"] == 1
assert data["runtime_isolation"] == "package-normalized"
```

Extend the exact `display_row` dictionary in `tests\test_result_hierarchy.py` with:

```python
"Generated Test Pre-Fix Executed": "1/1",
"Generated Test Post-Fix Executed": "1/1",
"Benchmark Tests Executed": "1/1",
```

- [ ] **Step 9: Run result tests and formatting**

```powershell
uv run pytest tests\test_evaluation_factories.py tests\test_result_hierarchy.py tests\test_result_serialization.py tests\test_result_writer.py tests\test_evaluation_summary.py -v
uv run ruff check --fix src\bcbench\results tests\conftest.py tests\test_evaluation_factories.py tests\test_result_hierarchy.py tests\test_result_serialization.py tests\test_result_writer.py tests\test_evaluation_summary.py
uv run ruff format src\bcbench\results tests\conftest.py tests\test_evaluation_factories.py tests\test_result_hierarchy.py tests\test_result_serialization.py tests\test_result_writer.py tests\test_evaluation_summary.py
```

Expected: all result, export, and summary tests pass.

- [ ] **Step 10: Commit**

```powershell
git add src\bcbench\results tests\conftest.py tests\test_evaluation_factories.py tests\test_result_hierarchy.py tests\test_result_serialization.py tests\test_result_writer.py tests\test_evaluation_summary.py
git commit -m "Record bug-fix verification evidence" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 6: Implement the Three Package-normalized Bug-fix Gates

**Files:**
- Modify: `src\bcbench\evaluate\bugfix.py`
- Modify: `tests\test_bugfix_pipeline.py`

- [ ] **Step 1: Replace pipeline mocks with structured output and summaries**

In `tests\test_bugfix_pipeline.py`, create helpers:

```python
from bcbench.evaluate.bugfix_output import GeneratedBugFixOutput
from bcbench.exceptions import BuildError, TestExecutionError
from bcbench.operations.test_execution import TestCaseResult, TestExpectation, TestIdentity, TestOutcome, TestRunSummary


def _summary(codeunit_id: int, names: set[str], outcome: TestOutcome) -> TestRunSummary:
    identities = tuple(TestIdentity(codeunit_id, name) for name in sorted(names))
    return TestRunSummary(
        requested=identities,
        discovered=identities,
        results=tuple(TestCaseResult(identity, outcome) for identity in identities),
    )


def _generated_output() -> GeneratedBugFixOutput:
    tests = (TestEntry(codeunitID=123, functionName=frozenset({"RegressionTest"})),)
    return GeneratedBugFixOutput(
        full_patch="full patch",
        fix_patch="fix patch",
        test_patch="test patch",
        app_projects=("App\\Layers\\W1\\BaseApp",),
        test_projects=("App\\Layers\\W1\\Tests\\SCM-Manufacturing",),
        tests=tests,
    )


def _configure_successful_evaluation(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr("bcbench.evaluate.bugfix.stage_and_get_diff", lambda _repo_path: "full patch")
    monkeypatch.setattr("bcbench.evaluate.bugfix.analyze_generated_bugfix_output", lambda *_args: _generated_output())
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.categorize_projects",
        lambda _paths: (
            ["App\\Layers\\W1\\Tests\\SCM"],
            ["App\\Layers\\W1\\BaseApp"],
        ),
    )
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.clean_project_paths",
        lambda _repo_path, paths: calls.append(("clean", tuple(paths))),
    )
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.set_runtime_version",
        lambda _repo_path, paths: calls.append(("runtime", tuple(paths))),
    )
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.build_and_publish_projects",
        lambda _repo_path, paths, *_args: calls.append(("build", tuple(paths))),
    )
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.apply_patch",
        lambda _repo_path, patch, _name: calls.append(("apply", patch)),
    )

    def run_generated_tests(_tests, expectation, _container, _repo_path):
        calls.append(("test", expectation))
        outcome = TestOutcome.FAIL if expectation is TestExpectation.ALL_FAIL else TestOutcome.PASS
        return _summary(123, {"RegressionTest"}, outcome)

    monkeypatch.setattr("bcbench.evaluate.bugfix.run_test_suite", run_generated_tests)

    def run_benchmark_tests(_entry, _container, _repo_path):
        calls.append(("benchmark", TestExpectation.ALL_PASS))
        return _summary(999, {"BenchmarkTest"}, TestOutcome.PASS)

    monkeypatch.setattr("bcbench.evaluate.bugfix.run_tests", run_benchmark_tests)
    return calls
```

- [ ] **Step 2: Write a failing exact-order success test**

Add:

```python
def test_bugfix_normalizes_discovered_projects_in_gate_order(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    calls = _configure_successful_evaluation(monkeypatch)

    BugFixPipeline().evaluate(context)

    assert calls == [
        ("clean", ("App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\SCM-Manufacturing")),
        ("runtime", ("App\\Layers\\W1\\BaseApp", "App\\Layers\\W1\\Tests\\SCM-Manufacturing")),
        ("build", ("App\\Layers\\W1\\BaseApp",)),
        ("build", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        ("apply", "test patch"),
        ("build", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        ("test", TestExpectation.ALL_FAIL),
        ("apply", "fix patch"),
        ("build", ("App\\Layers\\W1\\BaseApp",)),
        ("build", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        ("test", TestExpectation.ALL_PASS),
        ("clean", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        ("runtime", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        ("apply", context.entry.test_patch),
        ("build", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        ("build", ("App\\Layers\\W1\\Tests\\SCM",)),
        ("benchmark", TestExpectation.ALL_PASS),
    ]
```

Set the fixture entry test path to `App\Layers\W1\Tests\SCM` so this test proves that `SCM-Manufacturing` is discovered independently.

- [ ] **Step 3: Run the pipeline tests and verify they fail**

```powershell
uv run pytest tests\test_bugfix_pipeline.py -v
```

Expected: failures because the current pipeline neither reapplies the generated test patch nor normalizes discovered test projects.

- [ ] **Step 4: Add count conversion helpers**

In `src\bcbench\evaluate\bugfix.py`:

```python
def _requested_counts(test_entries: list[TestEntry] | tuple[TestEntry, ...]) -> PhaseCounts:
    return PhaseCounts(requested=sum(len(entry.functionName) for entry in test_entries))


def _summary_counts(summary: TestRunSummary) -> PhaseCounts:
    return PhaseCounts(
        requested=summary.requested_count,
        discovered=summary.discovered_count,
        executed=summary.executed_count,
    )
```

- [ ] **Step 5: Replace obsolete patch-splitting imports**

Remove `extract_file_paths_from_patch`, `separate_patches`, `get_config`, and `extract_tests_from_patch` imports from `src\bcbench\evaluate\bugfix.py`.

Add:

```python
from bcbench.evaluate.bugfix_output import analyze_generated_bugfix_output
from bcbench.operations import order_project_paths
from bcbench.operations.test_execution import TestExpectation, TestRunSummary
from bcbench.results.bugfix import BugFixResult, PhaseCounts
```

Keep `set_runtime_version` imported because every cleaned project root needs its runtime field restored before rebuilding.

- [ ] **Step 6: Replace the current patch extraction**

At the start of `evaluate()`:

```python
generated_patch = stage_and_get_diff(context.repo_path)
generated = analyze_generated_bugfix_output(context.repo_path, generated_patch)
declared_test_projects, declared_app_projects = categorize_projects(context.entry.project_paths)
app_projects = order_project_paths(declared_app_projects, generated.app_projects)
generated_test_projects = order_project_paths(declared_test_projects, generated.test_projects)
generated_only_test_projects = [
    project
    for project in generated_test_projects
    if project.replace("\\", "/").casefold()
    not in {path.replace("\\", "/").casefold() for path in declared_test_projects}
]
```

Initialize phase counts from the frozen selections:

```python
pre_fix = _requested_counts(generated.tests)
post_fix = _requested_counts(generated.tests)
benchmark = _requested_counts([*context.entry.fail_to_pass, *context.entry.pass_to_pass])
```

- [ ] **Step 7: Implement Gate 1**

```python
normalized_projects = [*app_projects, *generated_test_projects]
clean_project_paths(context.repo_path, normalized_projects)
set_runtime_version(context.repo_path, normalized_projects)
build_and_publish_projects(context.repo_path, app_projects, container, context.entry.environment_setup_version)
build_and_publish_projects(context.repo_path, generated_test_projects, container, context.entry.environment_setup_version)
apply_patch(context.repo_path, generated.test_patch, f"{context.entry.instance_id} generated test patch")
build_and_publish_projects(context.repo_path, generated_test_projects, container, context.entry.environment_setup_version)
pre_summary = run_test_suite(
    list(generated.tests),
    TestExpectation.ALL_FAIL,
    container,
    context.repo_path,
)
pre_fix = _summary_counts(pre_summary)
```

Only set `generated_test_pre_patch_failed = True` after `run_test_suite()` returns.

- [ ] **Step 8: Implement Gate 2**

```python
apply_patch(context.repo_path, generated.fix_patch, f"{context.entry.instance_id} generated fix patch")
build_and_publish_projects(context.repo_path, app_projects, container, context.entry.environment_setup_version)
build_and_publish_projects(context.repo_path, generated_test_projects, container, context.entry.environment_setup_version)
post_summary = run_test_suite(
    list(generated.tests),
    TestExpectation.ALL_PASS,
    container,
    context.repo_path,
)
post_fix = _summary_counts(post_summary)
```

Only set `generated_test_post_patch_passed = True` after the summary validates.

- [ ] **Step 9: Implement Gate 3**

```python
clean_project_paths(context.repo_path, generated_test_projects)
set_runtime_version(context.repo_path, generated_test_projects)
apply_patch(context.repo_path, context.entry.test_patch, f"{context.entry.instance_id} benchmark test patch")
if generated_only_test_projects:
    build_and_publish_projects(
        context.repo_path,
        generated_only_test_projects,
        container,
        context.entry.environment_setup_version,
    )
build_and_publish_projects(
    context.repo_path,
    declared_test_projects,
    container,
    context.entry.environment_setup_version,
)
benchmark_summary = run_tests(context.entry, container, context.repo_path)
benchmark = _summary_counts(benchmark_summary)
```

Create success with:

```python
result = BugFixResult.create_success(
    context,
    generated.full_patch,
    pre_fix=pre_fix,
    post_fix=post_fix,
    benchmark=benchmark,
)
```

- [ ] **Step 10: Preserve partial summaries on failure**

Track the active phase and Booleans before entering the gate `try` block:

```python
phase = "generated pre-fix"
generated_test_pre_patch_failed = False
generated_test_post_patch_passed = False
```

Set the Booleans only after their summaries validate. Update `phase` before Gate 2 and Gate 3.

Use this exception handling:

```python
except BuildError as error:
    result = BugFixResult.create_verification_failure(
        context,
        generated.full_patch,
        f"{phase} build or publish failed\n{error}",
        build=False,
        generated_test_pre_patch_failed=generated_test_pre_patch_failed,
        generated_test_post_patch_passed=generated_test_post_patch_passed,
        pre_fix=pre_fix,
        post_fix=post_fix,
        benchmark=benchmark,
    )
except TestExecutionError as error:
    if isinstance(error.summary, TestRunSummary):
        counts = _summary_counts(error.summary)
        if phase == "generated pre-fix":
            pre_fix = counts
        elif phase == "generated post-fix":
            post_fix = counts
        else:
            benchmark = counts

    result = BugFixResult.create_verification_failure(
        context,
        generated.full_patch,
        f"{phase} verification failed\n{error}",
        build=True,
        generated_test_pre_patch_failed=generated_test_pre_patch_failed,
        generated_test_post_patch_passed=generated_test_post_patch_passed,
        pre_fix=pre_fix,
        post_fix=post_fix,
        benchmark=benchmark,
    )
```

Keep the existing explicit handling for `EmptyDiffError`, `GeneratedOutputError`, `NoTestsExtractedError`, and the `finally` block that saves exactly one result. Do not infer the failed phase only from Booleans.

- [ ] **Step 11: Add failure-path tests**

Replace the existing transition-failure parameterization with summaries that raise:

```python
TestExecutionError(
    TestExpectation.ALL_FAIL,
    reason="Expected all tests to fail",
    summary=_summary(123, {"RegressionTest"}, TestOutcome.PASS),
)
```

for the pre-fix case and:

```python
TestExecutionError(
    TestExpectation.ALL_PASS,
    reason="Expected all tests to pass",
    summary=_summary(123, {"RegressionTest"}, TestOutcome.FAIL),
)
```

for the post-fix case. Add these assertions:

```python
def test_requested_counts_remain_when_pre_fix_build_fails(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    _configure_successful_evaluation(monkeypatch)
    monkeypatch.setattr(
        "bcbench.evaluate.bugfix.build_and_publish_projects",
        lambda *_args: (_ for _ in ()).throw(BuildError("App\\Layers\\W1\\BaseApp", "AL0000")),
    )

    BugFixPipeline().evaluate(context)

    result = _read_result(context)
    assert result.generated_test_requested_count == 1
    assert result.generated_test_pre_patch_discovered_count == 0
    assert result.generated_test_pre_patch_executed_count == 0
    assert result.generated_test_post_patch_discovered_count == 0
    assert result.benchmark_test_requested_count > 0


def test_generated_only_test_project_is_restored_before_hidden_tests(tmp_path, monkeypatch):
    context = create_evaluation_context(tmp_path)
    calls = _configure_successful_evaluation(monkeypatch)

    BugFixPipeline().evaluate(context)

    hidden_clean_index = calls.index(
        ("clean", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        calls.index(("test", TestExpectation.ALL_PASS)) + 1,
    )
    restore_index = calls.index(
        ("build", ("App\\Layers\\W1\\Tests\\SCM-Manufacturing",)),
        hidden_clean_index,
    )
    benchmark_index = calls.index(("benchmark", TestExpectation.ALL_PASS))
    assert hidden_clean_index < restore_index < benchmark_index
```

Adapt the existing `test_bugfix_rejects_invalid_generated_test_transition` cases to assert:

```python
assert result.error_message.startswith("generated pre-fix verification failed")
assert result.generated_test_pre_patch_executed_count == 1
```

for mixed pre-fix outcomes, and:

```python
assert result.error_message.startswith("generated post-fix verification failed")
assert result.generated_test_pre_patch_failed is True
assert result.generated_test_post_patch_passed is False
```

for post-fix failures. Adapt the hidden benchmark failure test to provide a failing `TestRunSummary` and assert its requested/discovered/executed counts are persisted.

- [ ] **Step 12: Run focused tests and formatting**

```powershell
uv run pytest tests\test_bugfix_pipeline.py tests\test_bugfix_output.py tests\test_project_categorization.py tests\test_test_execution.py -v
uv run ruff check --fix src\bcbench\evaluate\bugfix.py tests\test_bugfix_pipeline.py
uv run ruff format src\bcbench\evaluate\bugfix.py tests\test_bugfix_pipeline.py
```

Expected: all bug-fix pipeline and supporting tests pass.

- [ ] **Step 13: Commit**

```powershell
git add src\bcbench\evaluate\bugfix.py tests\test_bugfix_pipeline.py
git commit -m "Normalize bug-fix evaluator projects per gate" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 7: Version and Document the Corrected Methodology

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `uv.lock:247-248`
- Modify: `docs\bug-fix.md:7-10`
- Modify: `tests\test_version.py`

- [ ] **Step 1: Write the version expectation**

Add to `tests\test_version.py`:

```python
def test_corrected_dual_verification_uses_major_methodology_version():
    assert get_benchmark_version() == "1.0.0"
```

- [ ] **Step 2: Run the test and verify it fails**

```powershell
uv run pytest tests\test_version.py -v
```

Expected: failure showing current version `0.11.0`.

- [ ] **Step 3: Bump the benchmark version**

Change `pyproject.toml`:

```toml
version = "1.0.0"
```

- [ ] **Step 4: Update bug-fix documentation**

Replace the opening paragraph in `docs\bug-fix.md` with:

```markdown
The system is tasked with fixing a bug in the Business Central (AL) codebase and adding a focused regression test from an issue description. A task is resolved only when every generated test is discovered and executed, every generated test fails against package-normalized baseline applications, the identical tests pass after the generated fix, and the independent benchmark tests pass after generated test changes are removed.

Package normalization republishes touched baseline applications inside the existing container. It prevents agent-published app binaries from contaminating evaluator gates, but it does not restore database data, schema changes, or install-trigger side effects.
```

- [ ] **Step 5: Refresh the lock file**

```powershell
uv lock
```

Expected: the editable `bcbench` package entry in `uv.lock` changes from `0.11.0` to `1.0.0` without unrelated dependency upgrades.

- [ ] **Step 6: Run version tests**

```powershell
uv run pytest tests\test_version.py -v
```

Expected: all version tests pass.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml uv.lock docs\bug-fix.md tests\test_version.py
git commit -m "Version package-normalized bug-fix methodology" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Task 8: Run Complete Verification

**Files:**
- No new files expected.

- [ ] **Step 1: Run the targeted evaluator suite**

```powershell
uv run pytest tests\test_project_categorization.py tests\test_bugfix_output.py tests\test_test_execution.py tests\test_ps_templates.py tests\test_bugfix_pipeline.py tests\test_evaluation_factories.py tests\test_result_hierarchy.py tests\test_result_serialization.py tests\test_result_writer.py tests\test_evaluation_summary.py tests\test_version.py -v
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the full Python test suite**

```powershell
uv run pytest -q
```

Expected: exit code 0 with no failures.

- [ ] **Step 3: Run repository lint and format checks**

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pre-commit run --all-files
```

Expected: every command exits 0.

- [ ] **Step 4: Review the final diff**

```powershell
git --no-pager diff 81657d33..HEAD --stat
git --no-pager diff 81657d33..HEAD --check
git --no-pager status --short
```

Expected: only planned files are changed, `diff --check` is silent, and the working tree is clean.

## Task 9: Replay Run 34477586948

**Files:**
- Temporary artifacts only under `.bcbench\replay-34477586948`; do not commit them.
- Update after replay: `C:\Users\ventselartur\OneDrive - Microsoft\Agentic Development\Bugfixing\Offline evals\2026-09-10 BC-Bench dual fix-test evaluation review (run 34477586948).md`

- [ ] **Step 1: Download the four result artifacts**

```powershell
New-Item -ItemType Directory -Path .bcbench\replay-34477586948 -Force | Out-Null
gh run download 34477586948 -n evaluation-results-34477586948-microsoftInternal__NAV-212355 -D .bcbench\replay-34477586948\NAV-212355
gh run download 34477586948 -n evaluation-results-34477586948-microsoftInternal__NAV-213683 -D .bcbench\replay-34477586948\NAV-213683
gh run download 34477586948 -n evaluation-results-34477586948-microsoftInternal__NAV-214825 -D .bcbench\replay-34477586948\NAV-214825
gh run download 34477586948 -n evaluation-results-34477586948-microsoftInternal__NAV-214926 -D .bcbench\replay-34477586948\NAV-214926
```

Expected: each directory contains one per-instance JSONL result whose `output` field is the frozen generated patch.

- [ ] **Step 2: Extract the four patches**

Run this PowerShell command:

```powershell
Get-ChildItem .bcbench\replay-34477586948 -Recurse -Filter *.jsonl | ForEach-Object {
    $result = Get-Content $_.FullName -Raw | ConvertFrom-Json
    $patchPath = Join-Path $_.DirectoryName "$($result.instance_id).patch"
    Set-Content -Path $patchPath -Value $result.output -Encoding UTF8
}
```

Expected: one `.patch` file beside each JSONL file.

- [ ] **Step 3: Create the temporary replay runner**

Create `.bcbench\replay-34477586948\replay_patch.py` with:

```python
import argparse
import os
from pathlib import Path

from bcbench.evaluate.bugfix import BugFixPipeline
from bcbench.operations import apply_patch
from bcbench.types import AgentHarness, ContainerConfig, EvaluationCategory, EvaluationContext


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry-id", required=True)
    parser.add_argument("--patch-file", type=Path, required=True)
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--result-dir", type=Path, required=True)
    args = parser.parse_args()

    category = EvaluationCategory.BUG_FIX
    entry = category.entry_class.load(category.dataset_path, entry_id=args.entry_id)[0]
    context = EvaluationContext(
        entry=entry,
        repo_path=args.repo_path,
        result_dir=args.result_dir,
        container=ContainerConfig(
            name=os.environ["BC_CONTAINER_NAME"],
            username=os.environ["BC_SERVER_USERNAME"],
            password=os.environ["BC_SERVER_PASSWORD"],
            company=os.environ["BC_COMPANY"],
            server_url=os.environ["BC_SERVER_URL"],
            server_instance=os.environ["BC_SERVER_INSTANCE"],
        ),
        model="claude-opus-5",
        agent_name=AgentHarness.CLAUDE,
        agent_version="2.1.221",
        category=category,
    )

    pipeline = BugFixPipeline()
    pipeline.setup(context)
    apply_patch(
        args.repo_path,
        args.patch_file.read_text(encoding="utf-8-sig"),
        f"{args.entry_id} saved generated patch",
    )
    pipeline.evaluate(context)


if __name__ == "__main__":
    main()
```

Do not commit this script.

- [ ] **Step 4: Run one clean replay job per entry**

Run these commands on a `GitHub-BCBench` runner after performing the same Azure OIDC login and artifact-cache setup used by `.github\actions\setup-bc-container-repo\action.yml`:

```powershell
$entries = @(
    "microsoftInternal__NAV-212355",
    "microsoftInternal__NAV-213683",
    "microsoftInternal__NAV-214825",
    "microsoftInternal__NAV-214926"
)

foreach ($entryId in $entries) {
    $shortId = $entryId.Split("-")[-1]
    $root = Resolve-Path ".bcbench\replay-34477586948"
    $entryDir = Join-Path $root "NAV-$shortId"
    $repoPath = Join-Path $entryDir "testbed"
    $resultDir = Join-Path $entryDir "replay-results"
    $patchFile = Get-ChildItem $entryDir -Filter *.patch | Select-Object -First 1
    $plainPassword = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 32 | ForEach-Object { [char]$_ })
    $securePassword = ConvertTo-SecureString $plainPassword -AsPlainText -Force

    $env:BC_CONTAINER_NAME = "bcbench-replay-$shortId"
    $env:BC_SERVER_URL = "http://$($env:BC_CONTAINER_NAME)"
    $env:BC_SERVER_INSTANCE = "BC"
    $env:BC_SERVER_USERNAME = "admin"
    $env:BC_SERVER_PASSWORD = $plainPassword
    $env:GITHUB_SHA = (git rev-parse HEAD)

    .\scripts\Setup-ContainerAndRepository.ps1 `
        -InstanceId $entryId `
        -Category bug-fix `
        -ContainerName $env:BC_CONTAINER_NAME `
        -Username $env:BC_SERVER_USERNAME `
        -Password $securePassword `
        -RepoPath $repoPath

    Import-Module BcContainerHelper -Force -DisableNameChecking
    Import-Module .\scripts\BCContainerManagement.psm1 -Force -DisableNameChecking
    $env:BC_COMPANY = Get-BCContainerCompany -ContainerName $env:BC_CONTAINER_NAME

    try {
        uv run python .bcbench\replay-34477586948\replay_patch.py `
            --entry-id $entryId `
            --patch-file $patchFile.FullName `
            --repo-path $repoPath `
            --result-dir $resultDir
    }
    finally {
        Remove-BcContainer -containerName $env:BC_CONTAINER_NAME
    }
}
```

Expected: every replay starts with a newly provisioned per-entry container, while each evaluator still uses package normalization between its own three gates. Each result contains nonzero requested/discovered/executed counts and the corrected evaluator SHA.

- [ ] **Step 5: Classify each replay result**

For each entry, record:

```text
generated pre-fix: requested / discovered / executed / outcomes
generated post-fix: requested / discovered / executed / outcomes
hidden benchmark: requested / discovered / executed / outcomes
```

Expected:

- Gate 1 no longer passes because of an agent-published fixed BaseApp.
- NAV-212355 runs the generated test from `SCM-Manufacturing`, not `SCM`.
- Any rejected solution has a real build, discovery, execution, or assertion reason.

- [ ] **Step 6: Mark the old run invalid**

Add this status immediately below the run metadata in `C:\Users\ventselartur\OneDrive - Microsoft\Agentic Development\Bugfixing\Offline evals\2026-09-10 BC-Bench dual fix-test evaluation review (run 34477586948).md`:

```text
Invalid evaluator run: agent-published application packages contaminated the pre-fix gate, and exact generated-test execution was not verified.
```

Do not relabel its `0.11.0` results as `1.0.0`.

- [ ] **Step 7: Remove temporary replay files**

```powershell
Remove-Item -LiteralPath .bcbench\replay-34477586948 -Recurse -Force
git --no-pager status --short
```

Expected: replay artifacts are removed and the repository working tree remains clean.
