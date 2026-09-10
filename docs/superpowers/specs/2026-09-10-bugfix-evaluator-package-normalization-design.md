# Bug-fix Evaluator Package Normalization Design

## Summary

BC-Bench bug-fix evaluation must verify that an agent-produced regression test:

1. Is discovered and executed.
2. Fails against baseline product code.
3. Passes against the generated product fix.
4. Does not participate in the independent hidden benchmark phase.

Run 34477586948 could not establish these facts because the evaluator reused a Business Central container containing agent-published fixes and selected test projects only from dataset metadata. The corrected evaluator will keep the existing container, but normalize every touched AL project to the source state required by each gate and verify exact test execution through BCContainerHelper discovery and JUnit results.

This is package-level normalization, not complete runtime isolation. It does not reset database data, schema side effects, or install-trigger effects left by the agent.

## Goals

- Remove agent-published product fixes before the generated pre-fix gate.
- Discover generated test projects from the changed files, including projects absent from `entry.project_paths`.
- Ensure every requested test function exists and executes exactly once per gate.
- Reject zero executions, missing functions, extra functions, and skipped tests.
- Require every generated test to fail before the fix and pass after the fix.
- Remove generated test changes from the installed test apps before hidden benchmark tests.
- Preserve useful per-phase execution counts in results.
- Release the methodology under benchmark version `1.0.0`.
- Persist the exact evaluator commit SHA for official runs.
- Replay the four patches from run 34477586948 after the correction.

## Non-goals

- Recreating the Business Central container between gates.
- Restoring a database or container checkpoint.
- Proving that a generated pre-fix failure is semantically relevant to the issue beyond the hidden benchmark correctness gate.
- Redesigning the test-generation category.
- Introducing the full structured phase-status result model proposed in the evaluation review.
- Generalizing container provisioning into a reusable lifecycle abstraction.

## Current Defects

### Source cleanup does not restore installed apps

`clean_project_paths()` restores Git files only. It does not replace applications already published by the agent. The current pre-fix phase therefore can run baseline source tests against a fixed BaseApp still installed in the container.

### Dataset project paths do not identify every generated test project

The evaluator categorizes only `entry.project_paths`. A generated test under `App\Layers\W1\Tests\SCM-Manufacturing` is not published when the entry lists `App\Layers\W1\Tests\SCM`.

### Aggregate pass/fail does not prove execution

`Run-TestsInBcContainer` currently returns one Boolean. The evaluator does not verify that requested functions were discovered, executed, or unskipped. A missing function can therefore appear as a successful run.

### Boolean result fields hide why a phase failed

The current three gate Booleans cannot distinguish a real assertion outcome from missing tests, zero executions, or a phase that was never reached.

## Design Decisions

### Keep one container and normalize installed packages

The evaluator will not recreate the container. Before each gate, it will make the relevant source trees and installed application packages match the intended baseline, fixed, generated-test, or hidden-test state.

This directly repairs the observed defects while avoiding a new container lifecycle abstraction. The result must describe this isolation level as `package-normalized`, not fully clean runtime isolation.

### Resolve project ownership using the nearest `app.json`

Project ownership will be derived from the checked-out filesystem:

1. Parse every changed `.al` path in the frozen patch.
2. Resolve the path under the repository root and reject paths that escape it.
3. Walk from the file's parent toward the repository root.
4. Use the first directory containing `app.json` as the owning AL project.
5. Return repository-relative project roots in deterministic order.

This works for both NAV Layers and BCApps app/test layouts without encoding their directory depths.

The existing `find_project_paths_from_diff()` path-shape heuristic is not sufficient because it does not verify that the inferred directory is a real AL project.

### Classify the patch by owning project

The full staged agent patch is frozen before any cleanup. Each patched file is associated with its owning project and classified as product or test code using the existing complete-path-component test-project rules.

The analyzer produces:

- the complete generated patch;
- the frozen product-fix patch;
- the frozen generated-test patch;
- touched product project roots;
- touched generated-test project roots;
- exact generated test identities as `(codeunit ID, function name)`.

Evaluation fails before building when:

- a changed `.al` file has no owning `app.json`;
- no product-code change exists;
- no newly added `[Test]` procedure exists;
- a generated test cannot be associated with a discovered test project.

Generated test projects are allowed to differ from dataset-declared test projects.

### Use exact discovery and JUnit evidence

For each `TestEntry`, the test runner will:

1. Call `Get-TestsFromBcContainer` for the requested codeunit.
2. Compare the returned test names with the exact requested function names.
3. Fail if any requested function is missing.
4. Run the requested functions with `Run-TestsInBcContainer`.
5. Write JUnit XML to a unique temporary file under the repository path shared with the container.
6. Parse `<testcase>` elements and associate them with the codeunit and function identity.
7. Compare identity multisets, not only sets, so every requested function must execute exactly once.
8. Fail if an identity is missing, duplicated, or unexpectedly executed.
9. Fail if any test is skipped.
10. Delete the temporary result file in `finally`.

Running one JUnit result per codeunit avoids ambiguity when different codeunits contain functions with the same name.

Console text is diagnostic only. JUnit is the execution evidence.

## Evaluator State Machine

### Phase 0: Capture generated output

1. Stage and freeze the complete agent patch.
2. Resolve project ownership and split product/test changes.
3. Extract and freeze the exact generated test identities.
4. Record touched product and generated-test project roots.

No subsequent phase re-extracts tests from a modified workspace.

### Gate 1: Generated tests against baseline product code

1. Clean all touched product and generated-test project roots to Git baseline.
2. Build and publish baseline touched product projects.
3. Build and publish baseline versions of touched generated-test projects.
4. Apply only the frozen generated-test patch.
5. Build and publish the generated-test projects last.
6. Discover the exact generated test identities.
7. Run the exact generated tests.
8. Require:
   - requested count is greater than zero;
   - discovered identities equal requested identities;
   - executed identities equal requested identities;
   - skipped count is zero;
   - every generated test outcome is `Fail`.

Publishing baseline versions of touched test projects before applying the generated patch removes dependency on any test app the agent published during its session.

### Gate 2: Generated tests against the generated fix

1. Keep the frozen generated-test patch applied.
2. Apply the frozen product-fix patch.
3. Build and publish touched product projects.
4. Build and publish the same generated-test projects last.
5. Discover and run the identical frozen generated test identities.
6. Require:
   - discovered identities equal requested identities;
   - executed identities equal requested identities;
   - skipped count is zero;
   - every generated test outcome is `Pass`.

The requested test set cannot change between Gate 1 and Gate 2.

### Gate 3: Hidden benchmark tests against the generated fix

1. Clean every generated-test project root to Git baseline.
2. Keep the generated product fix applied.
3. Apply the trusted hidden benchmark test patch.
4. Determine the dataset benchmark test projects.
5. Publish baseline generated-test projects that do not contain hidden changes, removing generated test functions from their installed apps.
6. Publish benchmark test projects after applying the hidden patch.
7. Discover and run every selected fail-to-pass and pass-to-pass benchmark test.
8. Require:
   - discovered identities equal requested identities;
   - executed identities equal requested identities;
   - skipped count is zero;
   - every benchmark test outcome is `Pass`.

If a generated-test project is also a benchmark test project, it is cleaned once, receives only the hidden patch, and is published once.

## Project Publication Order

For the replay fix:

- product projects are published before test projects;
- generated or benchmark test projects are published last;
- the order from `entry.project_paths` is preserved for declared projects;
- additional discovered projects use deterministic repository-relative ordering.

The relevant dependencies are expected to be present in the baseline container. Building a full repository dependency graph is deferred because it is not required for the four replay entries.

## Test Run Model

The Python runtime will use an internal structured summary even though the persisted result keeps the existing Booleans.

Each test run summary contains:

- requested identities;
- discovered identities;
- executed identities;
- passed identities;
- failed identities;
- skipped identities.

The summary validates that the identity multisets are exact before the pipeline checks the expected outcome.

### Expected outcome rules

- Generated pre-fix: every requested test must fail.
- Generated post-fix: every requested test must pass.
- Hidden benchmark: every requested test must pass.

A mixed pre-fix result is rejected. Adding one failing test does not allow unrelated generated tests that already pass against baseline code.

## Persisted Result Changes

`BugFixResult` keeps:

- `generated_test_pre_patch_failed`;
- `generated_test_post_patch_passed`;
- `benchmark_test_passed`.

It adds:

- `generated_test_requested_count`;
- `generated_test_pre_patch_discovered_count`;
- `generated_test_pre_patch_executed_count`;
- `generated_test_post_patch_discovered_count`;
- `generated_test_post_patch_executed_count`;
- `benchmark_test_requested_count`;
- `benchmark_test_discovered_count`;
- `benchmark_test_executed_count`;
- `runtime_isolation`, set to `package-normalized`;
- `evaluator_commit_sha`.

Requested counts are populated from the frozen generated and benchmark selections before the gates run. Counts collected before a failure are preserved. A phase that was not reached therefore retains its requested count while its discovered and executed counts remain zero, together with a phase-specific error message.

Official GitHub Actions runs must populate `evaluator_commit_sha` from the evaluated workflow commit. Local runs may derive it from the BC-Bench checkout when available.

## Error Handling

### Project discovery errors

Errors identify the changed file and explain whether it escaped the repository, lacked an owning `app.json`, or belonged to an invalid project type.

### Build and publish errors

Errors include:

- gate name;
- source state being published;
- project path;
- underlying build or publish output.

The top-level `build` Boolean remains `false` when any required gate build or publish fails.

### Test selection errors

Selection errors include requested, discovered, and missing identities. Zero discovery and zero execution are always failures.

### Test execution errors

Execution errors include requested, executed, missing, extra, and skipped identities. Missing or malformed JUnit output is an infrastructure failure, not a test pass or fail.

### Outcome errors

Outcome errors identify the functions whose results did not match the gate rule. Pre-fix mixed outcomes are reported separately from missing or skipped tests.

## Benchmark Version and Provenance

The dual fix-test acceptance criteria are an evaluation methodology change. Under the repository versioning policy, the corrected methodology is released as `1.0.0`.

Results from the invalid `0.11.0` run must not be relabeled or aggregated with corrected results.

Every official result set records:

- benchmark version `1.0.0`;
- exact evaluator commit SHA;
- agent harness and version;
- model and experiment configuration;
- runtime isolation mode.

## Test Strategy

### Project discovery unit tests

- NAV product project under `App\Layers\W1\BaseApp`.
- NAV test project under `App\Layers\W1\Tests\SCM-Manufacturing`.
- BCApps `app` and `test` project layouts.
- Multiple changed files in one project.
- Multiple changed projects.
- New files.
- Missing `app.json`.
- Repository escape attempt.
- Deterministic ordering.

### Test evidence unit tests

- Every requested test fails.
- Every requested test passes.
- Mixed pre-fix outcomes.
- Missing requested function.
- Zero discovered tests.
- Zero executed tests.
- Extra executed function.
- Duplicate execution of a requested function.
- Skipped function.
- Duplicate function names in different codeunits.
- Missing JUnit file.
- Malformed JUnit XML.

### Pipeline orchestration tests

Tests record and assert the exact sequence of:

- patch capture;
- project discovery;
- project cleanup;
- patch application;
- project build and publication;
- generated pre-fix execution;
- generated post-fix execution;
- generated test removal;
- hidden patch application;
- hidden benchmark execution.

A regression test covers an entry declaring `SCM` while the generated test belongs to `SCM-Manufacturing`.

### Replay acceptance

The four saved patches from run 34477586948 are replayed with the corrected evaluator.

For every entry, artifacts must show:

- nonzero requested, discovered, and executed generated-test counts;
- every generated test failing at Gate 1;
- the identical generated tests passing at Gate 2 or a genuine fix failure;
- nonzero requested, discovered, and executed hidden-test counts;
- hidden benchmark outcomes;
- evaluator commit SHA and benchmark version `1.0.0`.

The replay is trustworthy for the observed package contamination and missing-test defects. It is not evidence of full database/runtime isolation.

## Rollout

1. Implement project ownership discovery and exact test evidence.
2. Refactor `BugFixPipeline` into the three explicit gates.
3. Add result counts and evaluator provenance.
4. Bump the benchmark version to `1.0.0`.
5. Run targeted unit and pipeline tests.
6. Replay the four saved patches.
7. Mark run 34477586948 invalid in the evaluation record.
8. Publish release notes that distinguish package normalization from full runtime isolation.

## Follow-up Work

Future work may introduce a reusable container lifecycle with clean database checkpoints, immutable application artifacts, dependency-topological publication, and fully structured phase statuses. Those changes are intentionally outside this replay-focused design.
