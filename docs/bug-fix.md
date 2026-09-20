---
layout: default
title: Bug Fixing - BC-Bench
---

# Bug Fixing

The system is tasked with fixing a bug in the Business Central (AL) codebase and adding a focused regression test from an issue description. A task is resolved only when the generated test fails before the generated fix and passes after it, and the independent benchmark test also passes with the generated fix.

The legacy workflow remains the default. The [opt-in production lifecycle](#opt-in-production-lifecycle) below adds database isolation and independent test/fix metrics; it is not yet approved for production promotion.

## Baseline Leaderboard

<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "average" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{% if agg.average != null %}{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}{% else %}N/A{% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

## MCP Server Experimental Configurations

Comparing experimental configurations for GitHub Copilot with **claude-opus-4.6**.

<table>
  <thead>
    <tr>
      <th>MCP Servers</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "average" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.model == "claude-opus-4-6" and agg.agent_name == "GitHub Copilot" %}
        {% unless agg.experiment.custom_instructions == true %}
    <tr>
      <td>{% if agg.experiment.mcp_servers %}{{ agg.experiment.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{% if agg.average != null %}{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}{% else %}N/A{% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}">{{ agg.benchmark_version }}</a></td>
    </tr>
        {% endunless %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>

## Opt-in production lifecycle

**Workflow:** [Opt-in production bug-fix evaluation](https://github.com/microsoft/BC-Bench/blob/main/.github/workflows/bugfix-production-evaluation.yml), file `.github\workflows\bugfix-production-evaluation.yml`. It runs only by explicit dispatch, uses `production: true` in summarization, and keeps `skip-leaderboard: true`. Do not change the default workflows or publish these results to the legacy leaderboard as part of a canary.

**Status:** documentation and operator preparation do not establish production readiness. Real-runner replay fixtures, checkpoint/fault rehearsals, and live canaries remain pending. The timeout-marked replay class also lacks a public input, described below. No production runner or frozen canary patches are supplied by this runbook.

### Methodology and metrics

The result's `runtime_isolation` is **`database-checkpointed-single-container`**, not the legacy `package-normalized`. Each invocation owns one container, trusted prepared source **O**, a clean baseline database checkpoint **S0**, and, after a successful generated fix build, a fixed database checkpoint **SF**. The agent's complete patch is frozen only after its process tree and managed MCP clients have stopped with verified shutdown. **T** is the generated test, **F** the generated fix, **G** the trusted gold fix, and **B** the independent benchmark tests.

| Phase field | Official evaluation |
| --- | --- |
| `test_red` | Restore S0; build/publish O + T. The exact generated test must execute and fail. `passed` means the expected red outcome was proved, not that the AL test passed. |
| `test_gold` | Restore S0; build/publish O + G + T. The same generated test must pass with the trusted gold fix. |
| `fix_build` | Restore S0; build/publish O + F without T or B, verify inventory, and capture SF. |
| `generated_pair` | Start from the verified fixed inventory immediately after fix-build; publish T against F. The exact test identity executed in red must now pass. |
| `benchmark_fix` | Restore SF to remove generated-test effects; publish B against F and require all requested fail-to-pass and pass-to-pass tests to pass. |

An invalid T does **not** suppress an independently valid F: fix-build and benchmark-fix still run when their prerequisites are available. Restores verify container identity, database topology, application inventory, authentication, company, endpoints, and test discovery, not just package filenames.

| Metric | Requirement |
| --- | --- |
| `GeneratedTestValidity` | `test_red` and `test_gold` pass. |
| `GeneratedPairTransition` | `test_red` and `generated_pair` pass. |
| `FixBuild` | `fix_build` passes. |
| `FixQuality` | `benchmark_fix` passes, independent of generated-test validity. |
| `Resolution` | Test validity, pair transition, and fix quality pass; a determined fix-build failure also determines Resolution failure. Agent timeout always prevents resolution. |

Each metric reports `successes`, `determined_failures`, `unknown`, `scheduled`, `rate`, and `coverage`. `passed` is success; `failed` and `invalid_submission` are determined failures; `infrastructure_error` and `not_run` are unknown. Required-status precedence is invalid submission, failure, infrastructure error, not run, then passed: a known failure is not hidden by another unknown prerequisite.

**Success rate** is successes / (successes + determined failures); **coverage** is (successes + determined failures) / scheduled. For 6 successes, 2 failures, and 2 unknowns, rate is **75%** and coverage **80%**. With no determined results, rate is null, not 0%; with no scheduled results, coverage is 0. These counts are **per metric**, not an entry-wide exclusion: unknown FixQuality need not erase known GeneratedTestValidity or Resolution. Compare scheduled entry IDs with produced results as well; a missing result file is not automatically a counted unknown.

An agent timeout preserves any safely frozen patch and any independently determined phase evidence. `timeout: true` forces Resolution to a **known failure**, even if other metrics remain unknown; a pre-existing `invalid_submission` classification retains precedence over `failed`. Timeout does not make all five metrics unknown or overwrite passing fix evidence. Build/test infrastructure timeouts are classified separately from agent timeout.

Legacy booleans remain projections: `generated_test_pre_patch_failed` means red passed, `generated_test_post_patch_passed` means pair passed, `build` means fix-build passed, `benchmark_test_passed` means benchmark-fix passed, and `resolved` means Resolution passed. The coarse `infrastructure_failure` is true only when **all five metrics** are unknown; use phase records and metric coverage instead of treating that Boolean as a per-entry denominator.

**Never aggregate isolation modes.** Keep `package-normalized` and `database-checkpointed-single-container` in separate summary/leaderboard combination keys. Keep deterministic `execution_mode: replay` evidence separate from live agent performance too. The [result/scoring model](https://github.com/microsoft/BC-Bench/blob/main/src/bcbench/results/bugfix.py) is the source of truth.

### Provisioning and command examples

Meet the [operator prerequisites](https://github.com/microsoft/BC-Bench/blob/main/README.md#isolated-bug-fix-lifecycle) first. The [setup action](https://github.com/microsoft/BC-Bench/blob/main/.github/actions/setup-bugfix-lifecycle/action.yml) invokes `scripts\Setup-BugFixLifecycle.ps1` and exports canonical `BCBENCH_LIFECYCLE_*` / `BC_*` values for later steps. It pins evaluator tools and prepares the exact dataset/version, restricted identities, read-only tool roots, and durable ownership handoff. In GitHub Actions it requires the `ado-read` environment and Azure OIDC permissions for internal repositories. Do not substitute a different dataset or hand-edit the ownership envelope after setup.

For **each** example below, provision a **new** invocation for `$InstanceId`, use its exported environment, and choose exactly one evaluation command. Reuse neither a cleaned container nor a quarantined root. The selected harness must be installed even for replay because the CLI reads its version. `--model claude-sonnet-5` is supported by both harness registries.

```powershell
# In the evaluator shell after setup for this exact $InstanceId:
Import-Module .\scripts\BugFixLifecycle.psm1 -Force -DisableNameChecking
Start-BCBenchWorkflowExecution -ProtectedRoot $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT `
  -ExpectedContainerId $env:BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID `
  -ExpectedInvocationId $env:BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID
# Record that handoff once per new invocation, then choose ONE command:
uv run --frozen --no-sync bcbench bugfix-lifecycle copilot $InstanceId `
  --model claude-sonnet-5 --dataset-path $env:BCBENCH_LIFECYCLE_DATASET_PATH `
  --output-dir C:\bcbench-results --run-id task14-copilot

# Alternative, on a separately provisioned invocation:
uv run --frozen --no-sync bcbench bugfix-lifecycle claude $InstanceId `
  --model claude-sonnet-5 --dataset-path $env:BCBENCH_LIFECYCLE_DATASET_PATH `
  --output-dir C:\bcbench-results --run-id task14-claude

# Alternative replay: setup used -ReplayPatch with an operator-supplied frozen patch.
uv run --frozen --no-sync bcbench bugfix-lifecycle copilot $InstanceId `
  --model claude-sonnet-5 --replay-patch $env:BCBENCH_LIFECYCLE_REPLAY_PATCH `
  --dataset-path $env:BCBENCH_LIFECYCLE_DATASET_PATH `
  --output-dir C:\bcbench-results --run-id task14-replay
```

The replay input is a complete frozen diff against that entry's trusted prepared source, not a fabricated gold fix/test pair. Setup copies `-ReplayPatch` into `<ProtectedRoot>\replay.patch`; the CLI's `--replay-patch` must be a regular file **inside the protected root**. Replay bypasses agent execution, not baseline setup, isolation checks, official phases, or cleanup. A replay run writes `execution_mode: replay`.

Keep result output outside both owned roots. Successful result persistence writes `<output-dir>\<run-id>\<instance-id>.jsonl` plus `<ProtectedRoot>\final-results\final-result.json`. Use a new run ID for independent attempts; do not infer successful evaluation from CLI exit code alone. Read the result and cleanup evidence. Always finalize even when setup/CLI fails:

```powershell
.\scripts\Complete-BugFixLifecycle.ps1 -EntryRoot $env:BCBENCH_LIFECYCLE_ENTRY_ROOT `
  -ProtectedRoot $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT `
  -ContainerName $env:BC_CONTAINER_NAME -TimeoutSeconds 180
```

The workflow allocates paths before setup and uses this finalizer in an `always()` step, so it does not depend on setup having exported a complete environment. For standalone operations use the same pattern:

<details markdown="1">
<summary>Standalone per-entry setup and guaranteed finalization (approved production runner only)</summary>

The public setup script writes environment exports to `GITHUB_ENV` / `GITHUB_OUTPUT`; it does **not** set the caller's process environment. This operator helper instead calls its exported PowerShell module entry point in-process and maps the returned setup context into process environment variables. No secret JSON configuration file or password-bearing subprocess argument is needed. This is a runbook helper, not a new `bcbench` command. Run from the benchmark checkout with all tools already provisioned and evaluator credentials injected as `BC_SERVER_USERNAME` / `BC_SERVER_PASSWORD`. Repository tokens, if needed, are `GH_TOKEN` and `ADO_TOKEN`. Do not log the returned setup context.

```powershell
function Invoke-PreparedCanary {
  param(
    [Parameter(Mandatory)][string]$InstanceId,
    [Parameter(Mandatory)][scriptblock]$Operation,
    [string]$ReplaySource = ''
  )
  $ErrorActionPreference = 'Stop'
  $pwsh = (Get-Command pwsh -ErrorAction Stop).Source
  if ($PSVersionTable.PSVersion.Major -lt 7 -or $pwsh -match '[\\/]WindowsApps[\\/]') {
    throw 'Native PowerShell 7 is required.'
  }
  if (!$env:BC_SERVER_USERNAME -or !$env:BC_SERVER_PASSWORD) {
    throw 'Inject evaluator BC credentials into the environment first.'
  }
  Import-Module .\scripts\BCBenchUtils.psm1 -Force -DisableNameChecking
  Import-Module .\scripts\BugFixLifecycle.psm1 -Force -DisableNameChecking
  $dataset = Get-BCBenchDatasetPath -Category bug-fix
  $python = uv run --frozen --no-sync python -c "import sys; print(sys.executable)"
  if ($LASTEXITCODE -ne 0) { throw 'Python resolution failed.' }
  $npmRoot = npm prefix -g
  if ($LASTEXITCODE -ne 0) { throw 'npm root resolution failed.' }
  $toolRoots = @(
    $npmRoot,
    (Split-Path (Split-Path (Get-Command git).Source -Parent) -Parent),
    (Split-Path (Get-Command node).Source -Parent),
    (Split-Path $pwsh -Parent),
    (Split-Path (Get-Command dotnet).Source -Parent),
    (Join-Path $HOME '.dotnet\tools')
  ) | Select-Object -Unique
  $id = [Guid]::NewGuid().ToString('N')
  $entryRoot = "C:\bcbench\entries\$id"
  $protectedRoot = "C:\bcbench-protected\$id"
  $containerName = "bcbench-$id"
  Write-Host "Entry=$InstanceId EntryRoot=$entryRoot ProtectedRoot=$protectedRoot Container=$containerName"
  $previous = @{}
  try {
    $setup = Invoke-BCBenchBugFixLifecycle -InstanceId $InstanceId -Category bug-fix `
      -DatasetPath $dataset -EntryRoot $entryRoot -ProtectedRoot $protectedRoot `
      -ContainerName $containerName -EvaluatorUsername $env:BC_SERVER_USERNAME `
      -EvaluatorPassword (ConvertTo-SecureString $env:BC_SERVER_PASSWORD -AsPlainText -Force) `
      -PythonExecutable $python -ToolRoots $toolRoots -WorkflowEvidence `
      -ReplayPatch $ReplaySource -GithubToken $env:GH_TOKEN -AdoToken $env:ADO_TOKEN `
      -GithubEnv '' -GithubOutput ''
    $values = @{
      BCBENCH_LIFECYCLE_ENTRY_ROOT = $setup.EntryRoot
      BCBENCH_LIFECYCLE_PROTECTED_ROOT = $setup.ProtectedRoot
      BCBENCH_LIFECYCLE_DATASET_PATH = $setup.DatasetPath
      BCBENCH_LIFECYCLE_AGENT_OS_USERNAME = $setup.AgentIdentity.Username
      BCBENCH_LIFECYCLE_AGENT_OS_PASSWORD = $setup.AgentIdentity.Password
      BCBENCH_LIFECYCLE_AGENT_OS_SID = $setup.AclTransaction.Sid
      BCBENCH_LIFECYCLE_AGENT_BC_USERNAME = $setup.AgentBcIdentity.Username
      BCBENCH_LIFECYCLE_AGENT_BC_PASSWORD = $setup.AgentBcIdentity.Password
      BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID = $setup.ContainerId
      BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID = $setup.ContainerInvocationId
      BCBENCH_LIFECYCLE_STAGED_WORKER_PATH = $setup.WorkerPath
      BCBENCH_LIFECYCLE_STAGED_WORKER_SHA256 = $setup.WorkerSha256
      BCBENCH_LIFECYCLE_BASE_PYTHON = $setup.PythonBaseExecutable
      BCBENCH_LIFECYCLE_PYTHON_BASE_PREFIX = $setup.PythonBasePrefix
      BCBENCH_LIFECYCLE_ACL_PATHS_JSON = (ConvertTo-Json -InputObject @($setup.AclTransaction.ModifiedPaths) -Compress)
      BCBENCH_LIFECYCLE_CLEANUP_TOOL_ROOTS_JSON = (ConvertTo-Json -InputObject @($setup.ToolRoots) -Compress)
      BCBENCH_LIFECYCLE_OWNED_COMPILER_HELPER_ROOTS = [string]::Join([IO.Path]::PathSeparator, [string[]]$setup.OwnedCompilerHelperRoots)
      BCBENCH_LIFECYCLE_REPLAY_PATCH = $setup.ReplayPatch
      BCBENCH_LIFECYCLE_EVALUATOR_CONTAINER_CONFIG = $null
      BCBENCH_LIFECYCLE_AGENT_CONTAINER_CONFIG = $null
      BCBENCH_LIFECYCLE_AL_MCP = 'false'
      BCBENCH_LIFECYCLE_AL_LSP = 'false'
      BCBENCH_LIFECYCLE_BC_MCP = 'false'
      BCBENCH_LIFECYCLE_REHEARSAL_ITERATIONS = '0'
      BC_CONTAINER_NAME = $setup.ContainerName
      BC_SERVER_URL = $setup.EvaluatorContainerConfig.server_url
      BC_SERVER_INSTANCE = $setup.EvaluatorContainerConfig.server_instance
      BC_COMPANY = $setup.Company
      BC_MCP_URL = $setup.BcMcpUrl
    }
    foreach ($name in $values.Keys) {
      $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
      [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
    }
    & $Operation $InstanceId
  }
  finally {
    try {
      $markers = @(
        (Join-Path $protectedRoot 'quarantine.json'),
        "$protectedRoot.quarantine.json",
        "$protectedRoot.cleanup-pending.quarantine.json"
      )
      if (@($markers | Where-Object { Test-Path -LiteralPath $_ }).Count) {
        throw "Quarantine retained; inspect $protectedRoot before any cleanup retry."
      }
      .\scripts\Complete-BugFixLifecycle.ps1 -EntryRoot $entryRoot `
        -ProtectedRoot $protectedRoot -ContainerName $containerName -TimeoutSeconds 180
    }
    finally {
      foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
      }
      $setup = $null
    }
  }
}
```

This helper deliberately leaves MCP/LSP off, matching default workflow inputs. For a tooling-enabled canary use the setup action's `al-mcp`, `al-lsp`, and `bc-mcp` inputs and its canonical exports, not ad-hoc credential configuration. The operation must record the execution handoff before spawning the lifecycle CLI, as below. The rehearsal script records its own handoff: do **not** call `Start-BCBenchWorkflowExecution` before it. Rehearsal also finalizes internally; the helper's repeated finalizer is safe only for verified successful cleanup, never a quarantine bypass. Retain the nonsecret allocation line to locate each invocation's evidence.

</details>

### Evidence and acceptance checks

The workflow separates artifacts so only `evaluation-results-*` are summarized:

| Artifact | Contents and retention |
| --- | --- |
| `evaluation-results-<run_id>-<entry>` | Result JSONL only; stable run/entry name with `overwrite: true` on rerun. Retained 1 day for `test-run`, otherwise 30. |
| `lifecycle-evidence-<run_id>-<run_attempt>-<entry>` | Protected `final-results\` plus `workflow-*.json`, attempt-specific; retained 1 day for `test-run`, otherwise 30. |
| `lifecycle-quarantine-<run_id>-<run_attempt>-<entry>` | All three quarantine marker locations if present; retained 30 days. |
| `rehearsal-evidence-<run_id>-<run_attempt>-<entry>` / `rehearsal-quarantine-<run_id>-<run_attempt>-<entry>` | Dedicated rehearsal evidence/markers, not leaderboard results; retained 30 days. |

`final-results\final-result.json` includes all five phase records, trusted-source and patch/checkpoint hashes, container provenance, evidence references, and an artifact hash manifest. Protected, content-addressed `final-results\artifacts\<kind>\<sha256>.<extension>` files include the frozen patch, preparation/isolation diagnostics, checkpoint manifests, built packages, expected/actual inventory evidence, compiler/publication output, exact requested/discovered/executed test identities, JUnit/discovery evidence, and available agent diagnostics. Follow each phase's `evidence` paths rather than assuming original filenames survive content addressing. Evidence from unexecuted phases is necessarily absent; their status and reason must still be present.

**Database backups stay protected on the runner and are not uploaded.** The result manifest can reference checkpoint files outside the uploaded `final-results\` subtree. It is a pre-cleanup manifest, not a claim that every reference is in the ZIP or that later cleanup succeeded. Inspect `final-results\cleanup.json` and `workflow-cleanup.json` separately; setup, launch, rehearsal, and cleanup handoffs live in `workflow-*.json`. Preserve evidence before short canary retention expires.

For every replay/live entry, reconcile the scheduled ID and fixture hash with the result, then check phase status, legacy projection, per-metric coverage, checkpoint provenance, exact test identity/counts, and expected/actual package inventories. Red/gold/fix-build use S0; pair uses the fixed inventory; benchmark-fix restores SF and must not contain generated-test packages. Confirm independent fix evaluation after an invalid T. Do not treat a missing JUnit file, duplicate execution, or unavailable restore as an ordinary failed AL assertion.

After finalization, verify container **absence by immutable ID and name**, owned-root/ACL/identity cleanup, and absence of **all three** markers. Example read-only checks, using `$protectedRoot` from that invocation (or recovered from its evidence):

```powershell
$setupRecord = Get-Content -LiteralPath (Join-Path $protectedRoot 'workflow-setup.json') -Raw | ConvertFrom-Json
$cleanup = Get-Content -LiteralPath (Join-Path $protectedRoot 'workflow-cleanup.json') -Raw | ConvertFrom-Json
if ($cleanup.status -ne 'success') { throw 'Cleanup was not successful.' }
$containers = @(docker ps -a --no-trunc --format json)
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify Docker inventory.' }
foreach ($row in $containers) {
  $container = $row | ConvertFrom-Json
  if ($container.ID -eq $setupRecord.ContainerId -or $container.Names -eq $setupRecord.ContainerName) {
    throw 'Owned container still exists.'
  }
}
foreach ($path in @(
  (Join-Path $protectedRoot 'quarantine.json'),
  "$protectedRoot.quarantine.json",
  "$protectedRoot.cleanup-pending.quarantine.json"
)) {
  if (Test-Path -LiteralPath $path) { throw "Quarantine requires review: $path" }
}
if (Test-Path -LiteralPath $setupRecord.EntryRoot) { throw 'Owned entry root remains.' }
```

These are necessary checks, not substitutes for phase evidence or verified Job Object drainage. If Docker inventory cannot be read, absence is **unverified**, not success. Inspect exact ACL transaction and restricted-identity cleanup evidence; do not clear unrelated ACLs or accounts.

### Deterministic replay procedure

Obtain reviewed, frozen **entry-specific** patches and record their SHA-256, source/dataset revision, expected test identity, and expected class before execution. They are **not available here**. Do not manufacture them by copying the trusted gold/benchmark patches, substitute a unit mock, or claim replay success from a schema test.

For each available class below, set `$InstanceId` to its dataset entry and `$ReplaySource` to the reviewed patch file, then run on a fresh provisioned runner invocation. With the standalone helper defined above:

```powershell
$runId = 'task14-replay-' + [Guid]::NewGuid().ToString('N')
Get-FileHash -LiteralPath $ReplaySource -Algorithm SHA256
Invoke-PreparedCanary -InstanceId $InstanceId -ReplaySource $ReplaySource -Operation {
  param($InstanceId)
  Start-BCBenchWorkflowExecution -ProtectedRoot $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT `
    -ExpectedContainerId $env:BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID `
    -ExpectedInvocationId $env:BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID
  uv run --frozen --no-sync bcbench bugfix-lifecycle copilot $InstanceId `
    --model claude-sonnet-5 --replay-patch $env:BCBENCH_LIFECYCLE_REPLAY_PATCH `
    --output-dir C:\bcbench-results --run-id $runId
  if ($LASTEXITCODE -ne 0) { throw 'Replay execution failed; inspect protected evidence.' }
}
```

These expected outcomes assume the fixture isolates the named condition and all other prerequisites work. Phase order below is **red / gold / fix-build / pair / benchmark**. `P` = passed, `F` = failed, `I` = invalid_submission, `N` = not_run. Legacy order is **pre / post / build / benchmark / resolved**.

| Frozen submission class | Expected phase evidence | Legacy booleans | Metric outcome and coverage |
| --- | --- | --- | --- |
| Full success | P / P / P / P / P; exact red failure, then gold/pair/benchmark passes | true / true / true / true / true | All five pass and are determined (100% coverage). |
| Invalid T, valid F | I / I / P / I / P; structural T rejection, but fixed package/SF and benchmark evidence still exist | false / false / true / true / false | Validity, transition, Resolution are invalid; FixBuild/FixQuality pass. All five determined. |
| Generated **fix** build failure, valid T | P / P / F / N / N; generated-product compiler failure, no SF, pair/benchmark state their missing prerequisite | true / false / false / false / false | Validity passes; FixBuild and Resolution fail. Transition/FixQuality unknown (0% coverage for those metrics), not fabricated test failures. |
| Wrong red outcome, otherwise valid pair/fix | F / P / P / P / P; exact generated test executed but passed on O | false / true / true / true / false | Validity/transition/Resolution fail; FixBuild/FixQuality pass. All five determined. |
| Timeout-marked otherwise successful patch | Intended: P / P / P / P / P plus `timeout: true` | true / true / true / true / false | Intended: first four pass, Resolution known failure. **Public replay cannot currently supply this marker.** |

**Timeout replay gap:** `--replay-patch` accepts only patch text. Neither lifecycle CLI nor `BugFixLifecycleRequest` provides a replay timeout/outcome input; `timeout` is set when a **live** runner raises `AgentTimeoutError`. There is no supported `--replay-timeout` flag or marker embedded in a patch. Replaying a patch captured after an actual timeout loses that timeout metadata and does not complete this gate. An approved public replay-outcome capability (with provenance/validation) or an explicitly revised gate is required from the controller before this fifth deterministic class can run. Editing result JSON after the fact is not acceptable evidence. No feature implementation is included in this documentation task.

### Checkpoint rehearsal and fault injection

The public script is [`scripts\Test-BugFixLifecycleCheckpoint.ps1`](https://github.com/microsoft/BC-Bench/blob/main/scripts/Test-BugFixLifecycleCheckpoint.ps1). Required parameters are `-ContainerName` and `-CheckpointPath`; `-Iterations` accepts **1..100** (default **10**); `-Fault` accepts only the values in the table below (default `None`). `CheckpointPath` is a **new manifest file** under the invocation's protected `checkpoints` directory, not a backup/directory or a `BCBENCH_LIFECYCLE_CHECKPOINTS` environment variable.

The rehearsal prepares/publishes the actual trusted baseline and captures clean official S0. It selects an **existing, trusted entry test app** from publication provenance, uninstalls that app to mutate inventory, and uses an invocation-owned **SQL probe** for schema/data mutations. It captures a **separate probe checkpoint** for restore cycles, verifies all database files are ONLINE and the exact probe/inventory/discovery is restored, then restores official S0 and proves the probe absent. **No new AL app, temporary AL fixture, or reserved object-ID range is needed.** Clean-S0 success must be durably verified before cleanup eligibility and before an ordinary canary agent starts.

Run the no-fault case on **two distinct representative entries**, each with fresh setup and **ten consecutive cycles**:

```powershell
# Inside an already prepared invocation:
.\scripts\Test-BugFixLifecycleCheckpoint.ps1 -ContainerName $env:BC_CONTAINER_NAME `
  -CheckpointPath (Join-Path $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT 'checkpoints\official-s0.json') `
  -Iterations 10 -Fault None
```

With `rehearsal: true`, the opt-in workflow gets the four-entry test-run sample, explicitly selects the first **two distinct sorted IDs**, and runs ten no-fault cycles on each before paid evaluation. Ordinary `test-run: true` evaluation entries separately set `BCBENCH_LIFECYCLE_REHEARSAL_ITERATIONS=1`, so each does **one** no-fault cycle before its agent. `test-run: false` sets this hook to 0. Dedicated rehearsal does not replace that ordinary hook and is **not** a five-entry live canary.

For each injected fault, use a **new invocation** and one cycle. Do not reuse a checkpoint path or a completed rehearsal. The script finalizes its own resources and intentionally throws for `CleanupFailure`; preserve that failure and inspect its evidence rather than suppressing it.

```powershell
$faults = @(
  'CorruptBackup', 'HashMismatch', 'ReadinessFailure', 'UnexpectedApp',
  'MissingJUnit', 'DuplicateDiscovery', 'DuplicateExecution',
  'ServiceRestartFailure', 'CleanupFailure'
)
foreach ($fault in $faults) {
  Invoke-PreparedCanary -InstanceId $InstanceId -Operation {
    param($InstanceId)
    .\scripts\Test-BugFixLifecycleCheckpoint.ps1 -ContainerName $env:BC_CONTAINER_NAME `
      -CheckpointPath (Join-Path $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT 'checkpoints\official-s0.json') `
      -Iterations 1 -Fault $fault
  }
}
```

`CleanupFailure` is last because its expected nonzero outcome stops this sequence. Any earlier unexpected failure must also stop it for inspection. In the workflow, faults are not a dispatch input; use the public script on the approved runner, not an invented workflow flag.

| Fault | Expected verified evidence / classification |
| --- | --- |
| `None` | All requested iteration records are `passed`, `verified: true`; clean S0/probe absence verified; script succeeds. |
| `CorruptBackup` | Staged backup corruption is rejected by the staged-hash check: `infrastructure_error`, not an AL failure. |
| `HashMismatch` | Modified expected manifest hash is rejected by the protected-hash check: `infrastructure_error`. |
| `ReadinessFailure` | Incomplete readiness is rejected before unsafe test execution: `infrastructure_error`. |
| `UnexpectedApp` | Unexpected readiness app inventory is rejected: `infrastructure_error`. |
| `MissingJUnit` | Missing JUnit selection/execution evidence is rejected: `infrastructure_error`. |
| `DuplicateDiscovery` | Duplicate discovery identity is rejected: `infrastructure_error`. |
| `DuplicateExecution` | Duplicate executed identity is rejected: `infrastructure_error`. |
| `ServiceRestartFailure` | A restore result that does not prove a genuine service restart is rejected: `infrastructure_error`. |
| `CleanupFailure` | Restore iteration itself passes. Finalizer deliberately retains the owned container; its real absence check fails. Script fails and `workflow-rehearsal-cleanup-fault.json` must record `verified: true`, `status: infrastructure_error`, and exact container/invocation ownership. Quarantine is expected. |

For the eight non-cleanup injected faults, successful **fault detection** yields `verified: true`, `status: infrastructure_error`, clean official S0, successful finalization, no container, and no quarantine; the script can succeed because it verified the expected failure. Fault verification is cause-specific, not acceptance of any exception.

Inspect `final-results\rehearsal\checkpoints.json`, `iteration-0001.json` through `iteration-0010.json` for the ten-cycle runs (one record for each single-fault run), and `clean-s0.json` (`verified: true`, `probe_absent: true`). `workflow-rehearsal.json` must show successful evidence validation and `worker_shutdown: verified`. Cleanup-fault evidence is separate from the iteration status.

**Quarantine-only-for-cleanup-failure applies to correctly detected injected cases with verified recovery.** An unexpected process exit, unverified worker drainage, failed official-S0 restore, or missing durable evidence must also fail closed and preserve/quarantine resources. The execution guard is active before baseline preparation; it must not launch restore/service-recovery subprocesses after an unverified operation. Never force deletion to satisfy a nominal no-quarantine expectation.

### Five-entry live canary and promotion

`uv run bcbench dataset list --category bug-fix --test-run` returns **four** sampled entries, not two or five. The existing workflow has no explicit entry-list/count input: `test-run: true` runs four; `false` selects the full dataset (currently 52). **Do not use `test-run: false` to get a fifth entry or call a four-entry run a five-entry canary.**

The supported exact-five path is **per-entry lifecycle CLI execution**, with separate setup/finalization per ID. Select five distinct reviewed IDs from the actual dataset, record the selection/revision before any paid execution, and keep one agent/model/tooling configuration for the run. This executable selection example chooses five sorted IDs; replace that selection with a reviewed representative five when appropriate, still enforcing the count:

```powershell
Import-Module .\scripts\BCBenchUtils.psm1 -Force -DisableNameChecking
$dataset = Get-BCBenchDatasetPath -Category bug-fix
$entries = @(Get-Content -LiteralPath $dataset | Where-Object { $_.Trim() } |
  ForEach-Object { ($_ | ConvertFrom-Json).instance_id } | Sort-Object -Unique | Select-Object -First 5)
if ($entries.Count -ne 5) { throw 'Exactly five distinct dataset entries are required.' }
$entries
$runId = 'task14-live-' + [Guid]::NewGuid().ToString('N')
# Requires operator approval, provisioned runner, and agent auth in ENV.
foreach ($entry in $entries) {
  Invoke-PreparedCanary -InstanceId $entry -Operation {
    param($InstanceId)
    $env:BCBENCH_LIFECYCLE_REHEARSAL_ITERATIONS = '1'
    Start-BCBenchWorkflowExecution -ProtectedRoot $env:BCBENCH_LIFECYCLE_PROTECTED_ROOT `
      -ExpectedContainerId $env:BCBENCH_LIFECYCLE_EXPECTED_CONTAINER_ID `
      -ExpectedInvocationId $env:BCBENCH_LIFECYCLE_EXPECTED_INVOCATION_ID
    uv run --frozen --no-sync bcbench bugfix-lifecycle copilot $InstanceId `
      --model claude-sonnet-5 --output-dir C:\bcbench-results --run-id $runId
    if ($LASTEXITCODE -ne 0) { throw 'Live canary execution failed; inspect evidence before continuing.' }
  }
}
```

Use `claude` instead of `copilot` for a separate approved Claude canary, not a mixed five-entry denominator. Archive all five protected evidence roots and result JSONL files manually for this CLI path; workflow artifact uploads do not run locally. Require five results with the chosen IDs and `execution_mode: live`, the one-cycle pre-agent rehearsal, phase/inventory/test evidence, and successful cleanup without quarantine. Success here means **valid evaluation and cleanup**, not requiring the agent to solve every task.

If GitHub Actions must own exact-five selection, an explicit-list/count workflow capability remains a **separate, unimplemented change**. The current four-entry dispatch can be an additional smoke run, but does not complete this gate. No dispatch or full-dataset run is part of documentation preparation.

**Promotion gates remain unchecked until the controller records real evidence:**

- [ ] Controller-owned targeted/full non-E2E tests, Ruff, and separate specification/quality/final reviews pass for the final revision.
- [ ] Real restricted-identity access denial and contained-process timeout leave no surviving children/grandchildren; native PowerShell cleanup is verified.
- [ ] Two representative entries each complete ten consecutive checkpoint cycles, all supported injected faults are correctly classified, and clean official S0 is verified.
- [ ] All five deterministic submission classes are replayed with reviewed fixtures; resolve the missing public timeout-marker capability first.
- [ ] Five distinct live entries have complete result/evidence/coverage and verified deletion with no unexplained infrastructure failures or quarantine.
- [ ] All five metric summaries have correct per-metric counts/rate/coverage, and isolation modes have distinct combination keys.
- [ ] Opt-in results remain excluded from leaderboard publication while the gates are pending.

After these gates and a separately approved complete production evaluation cycle without unexplained infrastructure, missing evidence, cleanup failures, or quarantine, promotion can switch the normal bug-fix workflow to the lifecycle, enable its five production evaluators, and publish only under its checkpointed isolation key. Removing the legacy path is a separate change. This runbook does not execute or approve promotion.

### Quarantine response

Check `<ProtectedRoot>\quarantine.json`, its sibling `<ProtectedRoot>.quarantine.json`, and sibling `<ProtectedRoot>.cleanup-pending.quarantine.json`. With the workflow's allocation these are under `C:\bcbench-protected`, using the same invocation GUID. A pending marker means cleanup did not complete its verified handoff; it is not safe to erase/retry blindly.

Stop scheduling work on the runner; retain container, owned workspaces, protected source/checkpoints/evidence, and exact ACL state. Inspect `workflow-setup.json`, execution/rehearsal/cleanup records, immutable container ID and invocation label, and restricted username/SID. An administrator must establish process/bridge drainage and ownership, and secure the exact restricted identity before authorizing targeted recovery. If safe contained execution is unavailable, the bounded cleanup supervisor records `identity_security.status: unverified` and manual containment is required: **the account may still be enabled**. Even `worker_shutdown: verified` alone does not prove identity removal or container deletion.

Do not restore after unverified process shutdown, relax ACLs, delete evidence/markers to obtain a pass, remove containers by a guessed name, or touch unrelated accounts/resources. Unexpected recovery failure is a blocked promotion gate, not a benchmark model failure. Preserve the original marker and audit trail for controller review; there is no public automatic quarantine-clear command.

### Isolation and transport details

Setup exports its resolved `-DatasetPath` as `BCBENCH_LIFECYCLE_DATASET_PATH` (`--dataset-path`); the CLI loads that exact file, never a category fallback. It must stay inside the setup's agent-denied benchmark tree without links/junctions. Setup probes read denial under the restricted identity. Lifecycle commands parse `--dataset-path` and `--output-dir` lexically, then validate after acquiring cleanup ownership; unreadable/device dataset paths or file-valued output directories cannot bypass cleanup. Malformed ownership envelopes retain raw quarantine evidence. Other commands keep their existing path behavior.

The restricted Windows Job Object uses an environment allowlist and invocation-owned profile. Production AL MCP is evaluator-owned stdio behind an unguessable loopback HTTP bridge; BC credentials are in the server environment, not agent MCP JSON. BC MCP similarly injects upstream authentication outside the agent. Official publication/tests receive evaluator passwords in child environment, not argv. Managed client shutdown is verified before freeze or official evaluation; transport or shutdown failures fail closed. Nonproduction AL MCP remains stdio.

BC MCP shutdown stops acceptance and cancels owned upstream/downstream sockets before its bounded join, including idle SSE relays with disconnected clients. Legacy shutdown also drains requests; lifecycle shutdown retains unverified thread/socket-close failures across repeated checks, including failed startup. Interrupted shutdown attempts remaining stoppers before propagating the original interruption. Wrapper watchdog, nonzero-exit, or invalid-response failures retain wrapper diagnostics but do not read child captures before verified Job Object drainage; temporary cleanup failures cannot replace that containment classification.

Initialization-time server messages use the initialization response stream, including requests needing a client reply before initialization completes. Unsolicited messages use a separate bounded buffer (256 events), GET reconnection, and `Last-Event-ID` replay. Buffer overflow, expired replay history, delivery deadlines, and incomplete/timed-out responses are transport failures, never empty successes.

Production AL LSP/configured plugins use setup-owned `agent-tools\plugins`, outside the benchmark checkout and evaluated repository. The restricted identity has read/execute but no modification access; setup records exact ACL paths and checks the invocation ownership marker before use/cleanup. Compiler/helper roots are similarly setup-owned and tracked. Nonproduction plugin paths are unchanged.

`tests\test_production_mcp_secrets.py` exercises shell inspection without changing host accounts. Its optional `e2e` case needs an explicitly provisioned disposable identity and readable runtime/worker via `BCBENCH_BRIDGE_TEST_USERNAME`, `BCBENCH_BRIDGE_TEST_PASSWORD`, `BCBENCH_BRIDGE_TEST_WORKSPACE`, `BCBENCH_BRIDGE_TEST_PYTHON`, and `BCBENCH_BRIDGE_TEST_WORKER`. On a dedicated runner only: `uv run --frozen --no-sync pytest tests\test_production_mcp_secrets.py -m e2e`. This neither provisions accounts nor validates a real BC server, and is not a replacement for the replay/rehearsal/live gates.

[← Back to Home](index.md)
