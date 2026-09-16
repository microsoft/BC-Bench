# Bug-Fix Single-Container Production Lifecycle Design

## Summary

BC-Bench will add an opt-in production evaluator for the bug-fix category that uses one Business Central container per dataset entry and database checkpoints between official phases.

The new evaluator will independently determine whether:

1. The generated regression test detects the original bug.
2. The generated regression test accepts the benchmark gold fix.
3. The generated fix satisfies the generated test.
4. The generated fix passes the benchmark tests without the generated test installed.

The lifecycle will remain bug-fix-specific. It will not add checkpoint concepts to the shared `EvaluationPipeline` abstraction or change the behavior of test-generation, data-query, or other categories.

One narrow shared-boundary change is required: agent subprocess execution must guarantee process-tree termination and support a restricted operating-system identity. Without that capability, the evaluator cannot prove that the agent and its descendants are frozen before protected checkpoints and evaluator workspaces are used.

## Goals

- Keep the Docker container ID unchanged for the complete evaluation of one bug-fix entry.
- Restore deterministic application, extension, schema, and test-data state between official phases.
- Treat agent-built packages and agent-reported test outcomes as diagnostic only.
- Reconstruct evaluator workspaces from trusted original source instead of cleaning and reusing the agent workspace.
- Require exact generated and benchmark test discovery and exactly one execution per requested identity.
- Validate the generated test against both the original product and the benchmark gold fix.
- Evaluate a safely separable generated fix against benchmark tests even when the generated test is invalid.
- Distinguish model failures, invalid submissions, infrastructure failures, and phases that could not safely run.
- Persist structured evidence after every phase.
- Destroy the container and entry-specific directories after evidence is copied to protected storage.
- Introduce the lifecycle through a separate bug-fix workflow before making it the default.

## Non-goals

- Generalizing database checkpoints across all BC-Bench categories.
- Changing the test-generation evaluator.
- Replacing the current bug-fix workflow before checkpoint, process-isolation, and cleanup behavior have been validated.
- Trusting package cleanup as a substitute for checkpoint restoration.
- Reusing the agent's mutable workspace for official evaluation.
- Adding a general workflow engine or generic phase framework.
- Preserving the current bug-fix runtime path indefinitely after the production lifecycle is stable.

## Current Boundaries

Container and repository provisioning currently happen in:

- `.github/actions/setup-bc-container-repo/action.yml`
- `scripts/Setup-ContainerAndRepository.ps1`

Agent setup and evaluation currently happen together through:

- `src/bcbench/commands/evaluate.py`
- `src/bcbench/evaluate/base.py`
- `src/bcbench/evaluate/bugfix.py`

`BugFixPipeline.evaluate()` begins after the agent has already used the container. It can normalize source and republish packages, but it cannot establish a protected pre-agent checkpoint, isolate evaluator credentials, guarantee process-tree termination, or own final container destruction.

The production lifecycle must therefore sit above the current bug-fix `evaluate()` method.

## Considered Architectures

### External workflow and PowerShell only

An external-only implementation would leave `src/bcbench` untouched and reproduce dataset loading, patch analysis, test selection, test evidence, scoring, and result serialization in workflow scripts.

This has the smallest package-level blast radius but creates duplicate untyped implementations of behavior already owned by BC-Bench. It would be suitable for a disposable checkpoint prototype, not a production evaluator.

### Bug-fix-specific production orchestrator

The selected design adds a separate bug-fix command and lifecycle service under `src/bcbench`. It reuses the existing dataset, agent, patch, build, test, and result abstractions without changing the shared pipeline lifecycle.

This keeps the production state machine typed and testable while making its bug-fix-only scope explicit.

### Shared evaluation lifecycle framework

A shared framework could add checkpoint services, phase hooks, evidence storage, and teardown to `EvaluationPipeline` and `EvaluationContext`.

This would have the largest blast radius and only one immediate consumer. It is deferred until another category has a concrete transactional-container requirement.

## Architecture

### Opt-in workflow

Add a separate workflow:

```text
.github/workflows/bugfix-production-evaluation.yml
```

The workflow will support the Copilot and Claude harnesses while accepting only the `bug-fix` category. It will retain the existing bug-fix workflows unchanged during validation.

The workflow will:

1. Provision the repository, container, identities, and protected storage.
2. Install the selected agent harness.
3. Invoke the bug-fix production lifecycle command.
4. Upload compact result JSONL and a separate evidence artifact.
5. Run cleanup verification even when the lifecycle command fails.
6. Mark the runner for quarantine when cleanup verification fails.

### CLI composition root

Add bug-fix-only commands with this shape:

```text
bcbench bugfix-lifecycle copilot <entry>
bcbench bugfix-lifecycle claude <entry>
```

Each command will:

1. Load a `BugFixEntry`.
2. Resolve evaluator and restricted-agent runtime configuration.
3. Select the concrete agent runner.
4. Construct `ProductionBugFixLifecycle`.
5. Inject the agent runner into the lifecycle.

The lifecycle service will not select agent implementations.

### Production lifecycle service

`ProductionBugFixLifecycle` owns the complete entry execution:

- trusted baseline preparation;
- checkpoint creation and restoration;
- agent execution and freeze;
- submission analysis;
- phase ordering;
- phase-result persistence;
- metric projection;
- final cleanup.

It is not an `EvaluationPipeline` subclass. The existing `BugFixPipeline` remains unchanged during the opt-in rollout.

### Collaborators

#### Submission freezer

`SubmissionFreezer` will:

- capture the complete Git delta, including additions, deletions, and renames;
- reject modifications outside allowed product and test projects;
- reject changes to evaluator, workflow, manifest, and hidden-input locations;
- require test-project changes to be additions relative to `O`, rejecting deletion, rename, or modification of pre-existing test code;
- split the immutable submission into generated product fix `F` and generated test `T`;
- require exactly one newly added test procedure;
- resolve each changed AL file to its nearest owning `app.json`;
- preserve patch, project, and test-identity hashes.

The existing `GeneratedBugFixOutput` analysis is the starting point. The production freezer adds the stricter scope audit and immutable evidence contract.

#### Trusted workspace builder

`TrustedWorkspaceBuilder` will:

- prepare normalized original source `O` in a disposable baseline workspace before the agent runs;
- store the trusted source snapshot outside agent-writable and container-mounted paths;
- remove the disposable baseline workspace before the agent starts;
- create unpredictable evaluator workspace names after the agent is frozen;
- construct each requested source state from `O` plus only the approved patches;
- verify source and patch hashes before every build;
- never clean and reuse `agent-workspace`.

#### Checkpoint manager

`CheckpointManager` will:

- stop and start the Business Central service tier under evaluator control;
- capture and restore `S0` and `SF`;
- keep checkpoint masters outside container mounts;
- use a random mounted directory only as temporary authenticated staging;
- hash and verify the protected checkpoint;
- run SQL backup verification;
- verify database, service, endpoint, company, package, and container integrity after restoration.

The checkpoint implementation will use BcContainerHelper database backup and restore operations. Package-only cleanup is not an allowed fallback.

#### Phase runner

`BugFixPhaseRunner` will build, publish, verify, discover, and execute one phase at a time. It will reuse the existing structured test-evidence model and require exact identity multisets with no missing, duplicate, unexpected, or skipped tests.

#### Evidence store

`EvidenceStore` will:

- write one atomic structured record after every phase;
- retain larger diagnostics as separate files;
- keep protected evidence after later failures or workflow cancellation;
- produce the compact final `BugFixResult` projection.

## Identity and Process Isolation

### Evaluator identity

The evaluator identity owns:

- evaluator Business Central credentials;
- Docker and BcContainerHelper access;
- trusted source and gold artifacts;
- checkpoint masters;
- evaluator workspaces;
- final evidence storage.

These credentials and paths must not be inherited by the agent process.

### Agent identity

The agent runs under a dedicated short-lived Windows identity that:

- can write only its workspace and agent-log directory;
- cannot read evaluator storage;
- cannot invoke Docker;
- receives only restricted Business Central or MCP credentials required by the experiment;
- is removed or disabled during final cleanup.

The child process environment will be constructed from an allowlist rather than inheriting the evaluator environment and removing selected variables.

### Process containment

Copilot, Claude, MCP servers, compiler processes, shells, and descendants launched for the agent must run under a Windows Job Object or equivalent process-tree abstraction.

Closing the process group on normal completion, timeout, or failure must terminate every descendant before evaluation begins. A test must prove that a child and grandchild process do not survive.

This is the only required shared agent-harness boundary change. Checkpoint and phase behavior remain bug-fix-specific.

## Storage Layout

The host uses an entry-specific root with separate trust boundaries:

```text
entry-root/
  baseline-workspace/       # Evaluator only; removed before agent execution
  agent-workspace/          # Agent writable
  agent-logs/               # Agent writable
  mounted-staging/          # Empty except during frozen evaluator operations
  evaluator-workspaces/     # Evaluator only; created after agent freeze
  evidence/                 # Evaluator only

protected-root/
  trusted-source/
  gold-artifacts/
  checkpoints/
  final-results/
```

`protected-root` is not mounted into the container and is not readable by the agent identity.

The container is created with explicit mounts for the entry-root paths needed for compilation or staging. The disposable baseline workspace is removed before the agent starts. Official evaluator workspaces do not exist until the agent process group is terminated.

Checkpoint transfer follows this sequence:

1. Stop the service tier.
2. Create a random staging directory.
3. Capture or copy the backup through staging.
4. Copy the backup to or from protected storage.
5. Verify the protected hash and SQL backup.
6. Empty and remove staging.
7. Start the service tier.
8. Run reset and readiness verification.

Evaluator workspaces are created with unpredictable names only after agent termination. Their source contents are verified against the trusted snapshot before use.

## Lifecycle

### Phase 1: Trusted baseline

1. Record Docker container and image IDs, hostname, mounts, artifact version, BcContainerHelper version, compiler/runtime versions, database topology, and file locations.
2. Normalize the disposable baseline workspace to `O`.
3. Build and publish the original product and test projects.
4. Wait for initialization and expected background work.
5. Record published and installed application inventories.
6. Capture, hash, protect, and verify `S0`.
7. Store the trusted source snapshot outside container mounts.
8. Remove the disposable baseline workspace.
9. Rehearse a complete restore during initial rollout.
10. Verify authenticated Business Central readiness.

### Phase 2: Agent run and submission freeze

1. Materialize the agent workspace from `O`.
2. Run the selected agent and MCP configuration under the restricted identity and process group.
3. On completion, timeout, or agent failure, block new requests and close the process group.
4. Verify no descendant or publishing client remains.
5. Stop the service tier to end server-side sessions.
6. Freeze and hash the complete workspace delta.
7. Audit and split the submission into `F` and `T`.
8. Persist submission evidence before official evaluation.

Agent timeout is recorded separately. The frozen patch is still evaluated for diagnostics, but a timed-out entry cannot receive a successful `Resolution` score even if every phase passes.

### Phase 3: Generated test on original product

Restore and verify `S0`, then construct:

```text
O + T
```

Build and publish the generated test project last. Discover and execute the exact generated test once. Require a genuine assertion failure caused by original behavior.

Persist `test_red`.

### Phase 4: Generated test on gold fix

Restore and verify `S0`, then construct:

```text
O + G + T
```

Publish the trusted gold product package and dependency closure, then publish `T` last. Discover and execute the same generated test once and require it to pass.

Run this phase whenever `T` is safe to apply, even when the red outcome was behaviorally wrong, to preserve diagnostic evidence.

Persist `test_gold`.

### Phase 5: Generated fixed state

Restore and verify `S0` regardless of generated-test results, then construct:

```text
O + F
```

Build and publish generated product projects in dependency order. Verify package identities, installation and synchronization state, absence of generated test packages, and absence of unexpected apps.

When deployment succeeds, capture, hash, protect, and verify `SF`.

Persist `fix_build`.

### Phase 6: Generated pair

Start directly from the newly captured `SF` state without immediately restoring it, then construct:

```text
O + F + T
```

Publish `T` last and execute the exact generated test once. Run this phase when the generated test executed successfully during `test_red`, even if it unexpectedly passed on `O`.

Persist `generated_pair`.

### Phase 7: Independent fix evaluation

Restore and verify `SF`, then construct:

```text
O + F + H
```

Verify that generated test source and packages are absent. Publish benchmark test apps last. Discover and execute every requested fail-to-pass and pass-to-pass identity exactly once and require all tests to pass.

This phase runs whenever `F` is safely separable and `SF` exists, regardless of `T` validity.

Persist `benchmark_fix`.

### Phase 8: Final evidence and destruction

1. Persist the final structured result.
2. Copy all evidence to protected final storage.
3. Stop remaining evaluator processes.
4. Remove the container.
5. Verify that the container no longer exists.
6. Remove entry-specific source, compiler, staging, and helper directories.
7. Remove or disable the restricted agent identity.
8. Mark the runner for quarantine if cleanup verification fails.

Do not restore `S0` before destroying the container.

## Phase Dependency Rules

| Phase | Required prerequisite | Runs after model failure? | Runs after infrastructure failure? |
|---|---|---:|---:|
| `test_red` | Safe generated test patch | N/A | No, if `S0` cannot be trusted |
| `test_gold` | Safe generated test patch | Yes | Yes, if `S0` can be independently restored |
| `fix_build` | Safe generated fix patch | Yes | Yes, if `S0` can be independently restored |
| `generated_pair` | Verified `SF` and generated test executed in `test_red` | Yes | No, when required state is unknown |
| `benchmark_fix` | Verified `SF` | Yes | No, when `SF` is unknown |

An invalid generated test does not block `fix_build` or `benchmark_fix`.

A behaviorally wrong red outcome does not block `test_gold`, `fix_build`, or `generated_pair`.

A failed checkpoint-integrity check blocks every phase that depends on that checkpoint. The evaluator does not continue from the current mutable state.

## Phase Status Model

Every phase has exactly one status:

```text
passed
failed
invalid_submission
infrastructure_error
not_run
```

### `passed`

The phase completed and met its expected build, package, discovery, execution, and outcome requirements.

### `failed`

The phase reached a determined model-code outcome that did not meet the requirement. Examples include a generated compilation error, a generated test passing on `O`, or a benchmark assertion failure on `O + F`.

### `invalid_submission`

The frozen submission violates a structural rule. Examples include unsafe patch separation, forbidden paths, missing product changes, missing or duplicate generated tests, or weakened existing tests.

### `infrastructure_error`

The evaluator cannot determine the model outcome because of checkpoint, service, authentication, platform, transport, evidence, runner, or evaluator failure.

### `not_run`

The phase cannot safely run because a required prior state is unknown. It is not used to hide a known model or submission failure.

## Result Model

The bug-fix result will add:

- agent execution outcome and timeout metadata;
- phase status records for `test_red`, `test_gold`, `fix_build`, `generated_pair`, and `benchmark_fix`;
- compact evidence references;
- generated fix and test patch hashes;
- `S0` and `SF` checkpoint hashes;
- container and evaluator provenance;
- per-metric outcome and coverage state;
- runtime isolation value `database-checkpointed-single-container`.

Each phase record includes:

- status;
- start and end timestamps;
- failure classification and diagnostic summary;
- source and patch hashes;
- checkpoint and container identity;
- package inventory reference;
- requested, discovered, and executed test identities;
- build, publication, standard output, standard error, and JUnit evidence references.

Larger evidence remains in the separate workflow artifact rather than being embedded in JSONL.

## Metric Derivation

### GeneratedTestValidity

Success requires:

```text
T is structurally valid
AND test_red = passed
AND test_gold = passed
```

### GeneratedPairTransition

Success requires:

```text
test_red = passed
AND generated_pair = passed
```

### FixBuild

Success requires:

```text
fix_build = passed
```

### FixQuality

Success requires:

```text
benchmark_fix = passed
```

### Resolution

Success requires:

```text
agent did not time out
AND GeneratedTestValidity = passed
AND GeneratedPairTransition = passed
AND FixQuality = passed
```

The generated fix is still evaluated after timeout, but timeout forces `Resolution` to a determined failure.

Because timeout itself determines `Resolution`, a timed-out entry remains a determined `Resolution` failure even when one or more diagnostic phases later have unknown infrastructure outcomes. The independent non-resolution metrics retain their own phase-based coverage.

## Legacy Projection

During rollout, existing result consumers continue to receive:

- `resolved`: `Resolution` success;
- `build`: `FixBuild` success;
- `generated_test_pre_patch_failed`: `test_red` success;
- `generated_test_post_patch_passed`: `generated_pair` success;
- `benchmark_test_passed`: `benchmark_fix` success.

The existing entry-level `infrastructure_failure` Boolean cannot represent partial phase coverage and must not drive bug-fix aggregate scoring for the production lifecycle.

## Bug-Fix Aggregate Summary

Add a bug-fix-specific summary selected through `EvaluationCategory.BUG_FIX.summary_class`.

For every metric it reports:

- success count;
- determined-failure count;
- unknown count;
- scheduled count;
- success rate over determined outcomes;
- coverage over scheduled outcomes.

`failed` and `invalid_submission` are determined failures.

`infrastructure_error` and `not_run` are unknown outcomes that reduce coverage.

The overall legacy pass rate is the `Resolution` rate over determined outcomes. Per-entry values used for pass-at-k exclude unknown `Resolution` outcomes.

Other categories continue using `ExecutionBasedEvaluationResultSummary`.

Bug-fix run and leaderboard combination keys include `runtime_isolation`, preventing package-normalized, database-checkpointed, and future isolation modes from being aggregated together.

During the opt-in stage, the workflow reports the five production metrics in its own summary and artifact. When the lifecycle becomes the default, the bug-fix evaluator/export mapping is updated to publish `GeneratedTestValidity`, `GeneratedPairTransition`, `FixBuild`, `FixQuality`, and `Resolution`.

## Error Handling

- Every external operation has a phase name and explicit timeout.
- Readiness uses bounded polling followed by required integrity checks.
- Build errors identify the source state, project, and package being processed.
- Test errors distinguish selection evidence, execution evidence, infrastructure, and assertion outcome.
- Missing or malformed JUnit and discovery evidence is infrastructure failure.
- Agent-provided results never substitute for missing evaluator evidence.
- Checkpoint restore or integrity failure never falls back to package cleanup.
- Cleanup errors are persisted and trigger runner quarantine instead of being silently ignored.
- Result persistence failures stop further destructive cleanup only long enough to write an emergency host-level diagnostic; cleanup is then attempted.

## Validation Strategy

### Unit and state-machine tests

Use mocked checkpoint, workspace, build, test, and evidence adapters to cover:

- every phase status;
- every dependency edge;
- invalid `T` with valid `F`;
- wrong red outcome with diagnostic gold and pair phases;
- `S0` and `SF` infrastructure failures;
- timeout with a passing frozen patch;
- partial evidence persistence;
- cleanup failure.

### Process-containment tests

A test agent launches a child and grandchild process. Tests cover normal exit, non-zero exit, and timeout. All descendant PIDs must be absent before evaluation begins.

The restricted identity must be unable to read protected evaluator files or invoke Docker.

### Checkpoint rehearsal

On the production runner:

1. Mutate installed apps, schema, and test data.
2. Restore `S0`.
3. Verify container ID, database files, app inventory, data, authentication, company, endpoint, and test discovery.
4. Repeat for at least ten consecutive successful restore cycles across two representative bug-fix entries.

Any unexplained mismatch resets the consecutive-success count.

### Fault injection

Inject:

- corrupted staging backup;
- protected hash mismatch;
- service restart failure;
- authentication/readiness failure;
- unexpected installed app;
- missing JUnit;
- duplicate discovery or execution;
- container removal failure.

Each fault must produce the specified infrastructure or invalid-submission outcome and must not become a model failure.

### Deterministic patch replay

The lifecycle will have an internal replay mode that accepts a frozen submission patch and skips agent execution.

Replay the same patches through the current and production evaluators. Compare:

- phase evidence;
- package state;
- generated and benchmark test identities;
- legacy result projection;
- expected methodology differences.

Live agent runs are not used for evaluator equivalence because model output is nondeterministic.

### Live canary

Run at least five representative bug-fix entries through the opt-in production workflow, including:

- a fully successful fix and test;
- an invalid generated test with a valid fix;
- a generated build failure;
- a generated-test behavioral failure;
- an agent timeout or injected infrastructure failure.

Promotion requires complete evidence, successful cleanup, and no unexplained infrastructure classification.

## Rollout

### Stage 1: Opt-in production workflow

Keep the current workflows unchanged and run deterministic replay, checkpoint rehearsal, fault injection, and the live canary through the new workflow.

This temporarily duplicates workflow maintenance and runner cost, but it contains risk and makes evidence inspection possible.

### Stage 2: Default bug-fix evaluator

After all validation gates pass, change the normal Copilot and Claude bug-fix workflow paths to invoke `bcbench bugfix-lifecycle`.

Other categories continue to use their existing commands and pipelines.

### Stage 3: Remove the old bug-fix runtime path

After one complete scheduled bug-fix evaluation cycle has:

- no unexplained infrastructure failures;
- no cleanup or quarantine events;
- complete evidence for every scheduled entry;
- expected metric and coverage summaries;

remove the old bug-fix evaluator runtime path to prevent mixed methodologies.

Historical results and artifacts remain unchanged and retain their original benchmark version and runtime-isolation metadata.

## Documentation

Update `docs/bug-fix.md` when the production lifecycle becomes the default. The documentation will explain:

- the five bug-fix metrics;
- success rate versus coverage;
- the single-container checkpoint isolation level;
- timeout scoring;
- evaluator and checkpoint provenance;
- why results from different runtime-isolation modes must not be aggregated together.

The opt-in workflow will remain documented as experimental until promotion.
