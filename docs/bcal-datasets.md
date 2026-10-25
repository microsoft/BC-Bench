# BCAL dataset panels

BC-Bench exposes two reviewed single-turn NL2AL panels for BCAL evaluation:

| Selection | Entries | Purpose |
|---|---:|---|
| `gold` | 110 | Default benchmark panel |
| `challenge` | 65 | Harder held-out panel |

The **Evaluation with bcal** workflow defaults to `gold` for both scheduled and manual runs. Manual runs can select either panel from the `dataset` input. The selected panel is included in the workflow run name, concurrency group, bc-eval run name, and bc-eval tags.

## Focused cohorts and repetitions

Checked-in cohort manifests under `dataset/cohorts/` select an explicit ordered subset of one NL2AL panel. The CLI validates that a cohort is nonempty, contains no duplicate IDs, targets the selected panel, and contains only IDs present in that panel. Invalid cohorts fail before the evaluation matrix starts.

List and validate a cohort locally:

```powershell
uv run bcbench dataset list --category nl2al --dataset gold --cohort 55-chat-completion-policy --repeat-count 2
```

Launch two independent repetitions with normal scoring and Kusto publication:

```powershell
gh workflow run bcal-evaluation.yml -R microsoft/BC-Bench `
  --ref esbenk-bcal-scenario-evidence `
  -f dataset=gold `
  -f cohort=55-chat-completion-policy `
  -f repeat-count=2 `
  -f bcal-package-selection=experiment-pinned `
  -f bcal-version=<exact-experimental-version> `
  -f external-model=gpt-55-chat `
  -f test-run=false
```

Each repetition executes every selected entry independently, uses its own result directory and artifacts, and invokes bc-eval separately. The repetitions therefore receive separate EvalRunIds in Kusto. Raw results and bc-eval metadata record `cohort_name`, `cohort_sha256`, `repetition_index`, and `repetition_count`.

Leaving `cohort` empty and `repeat-count` at `1` preserves the existing full-dataset behavior.

## Separate completion-review model

BCal evaluations can optionally use a separate model for completion diagnostics and final review while leaving `external-model` as the implementation model:

```powershell
gh workflow run bcal-evaluation.yml -R microsoft/BC-Bench `
  --ref esbenk-bcal-scenario-evidence `
  -f dataset=gold `
  -f external-model=gpt-55-chat `
  -f completion-review-model=gpt-56-reasoning-sol `
  -f test-run=false
```

Leaving `completion-review-model` empty preserves existing behavior. The configured value is recorded as `completion_review_model` in raw results and bc-eval metadata, separately from the generation `model` and `judge_model`.

## Dataset source and freshness

BC-DeveloperExperience is the source of truth for the `candidate-v2` BCAL datasets. BC-Bench keeps a reviewed snapshot so evaluations remain reproducible and do not depend on another repository at runtime.

`dataset/nl2al_manifest.json` records the source dataset name and the date the snapshot was synchronized. It deliberately does not expose private repository URLs or internal revision identifiers. The per-panel SHA-256 values identify the exact public content evaluated.

Treat the committed JSONL files as vendored data:

1. Make dataset changes in BC-DeveloperExperience.
2. After those changes merge, copy each changed panel into `dataset/`.
3. Update the manifest version, synchronization date, counts, and SHA-256 values, plus `NL2ALDataset.version`.
4. Run the NL2AL panel and BCAL workflow tests.

The synchronization date is provenance, not a guarantee that the snapshot is current. When BC-DeveloperExperience has newer merged dataset changes, refresh BC-Bench before starting an evaluation intended to include them.

## BCAL package version

The workflow combines channel and version mode into one package selection:

- **`official-latest`** (default): installs the latest prerelease from the official feed and records the BCAL source branch as `master`.
- **`official-pinned`**: installs an exact version from the official feed.
- **`experiment-pinned`**: installs an exact package from the configured experimental `@Local` feed and records the originating BC-DeveloperExperience branch or PR.

Pinned selections require an exact NuGet version in `bcal-version`, including an optional fourth numeric component, prerelease suffix, or build metadata. `official-latest` requires the version field to be empty. Empty pinned versions, floating versions, and ranges are rejected before `dotnet` runs.

There is no experimental-latest option because the feed contains packages from multiple branches and PRs. `experiment-pinned` requires the `BCAL_TEST_FEED_URL` repository secret to point to the experimental `@Local` feed.

Before starting the matrix, BC-Bench verifies that the exact experimental package was published directly from BC-DeveloperExperience and derives its branch or `pr/<number>` identity.

Every official matrix job resolves and installs its own package version; experimental jobs install the exact requested pin. Raw results record the verified installed version as `agent_version`.

Local `evaluate bcal` performs the same global-tool discovery. Use `--bcal-version <exact-version>` or set `BCAL_PACKAGE_VERSION` to require the installed version to match an expected value:

```powershell
uv run bcbench evaluate bcal <instance-id> --dataset gold --bcal-version 18.0.38.47039-beta
```

## Local usage

```powershell
uv run bcbench dataset list --category nl2al --dataset gold
uv run bcbench dataset list --category nl2al --dataset challenge
uv run bcbench dataset view <instance-id> --category nl2al --dataset challenge
uv run bcbench dataset version <instance-id> --category nl2al --dataset challenge

# Generation only
uv run bcbench run bcal <instance-id> --dataset challenge

# Generation plus raw evaluation result
uv run bcbench evaluate bcal <instance-id> --dataset challenge

# Validate and summarize a completed run
uv run bcbench result summarize --run-id <run-id> --category nl2al --dataset challenge
```

`dataset version` writes both the Business Central version and the exact selected JSONL path when `--github-output` is used. The workflow passes that path to symbol resolution, so a challenge entry is never resolved against the gold file.

## Identity and scoring provenance

Every named-panel raw result records:

- `dataset`: `gold` or `challenge`
- `dataset_version`: the reviewed dataset revision from `dataset/nl2al_manifest.json`
- `dataset_sha256`: the exact SHA-256 of the selected JSONL at evaluation time

Summarization loads prompts and expected assertions from that same panel. It refuses to export results when the requested panel differs from the recorded panel, a named-panel result lacks identity, the JSONL hash changed, the recorded dataset version is wrong, or the result ID is absent from the selected panel.

Older results without panel identity keep their legacy behavior when summarization does not name a panel. They are not automatically labeled as gold.

Each named-panel bc-eval row includes:

| Metadata | Value |
|---|---|
| `agent_version` | Actual installed BCAL NuGet package version |
| `bcal_package_source` | `official` or `experiment` |
| `bcal_package_branch` | `master` or the provenance-derived BC-DeveloperExperience source branch |
| `bcal_package_feed` | `DynamicsSMBPackages` or `DynamicsSMBTest@Local` |
| `dataset`, `dataset_version`, `dataset_sha256` | Exact panel identity |
| `cohort_name`, `cohort_sha256` | Checked-in focused cohort identity, or `null` for full-panel runs |
| `repetition_index`, `repetition_count` | Independent repetition identity |
| `completion_review_model` | Optional BCal completion diagnostic/final reviewer model, separate from generation and judge models |
| `dataset_mode` | `single_turn` |
| `dataset_turn_count` | `1` |
| `evaluation_scope` | `single_turn` |
| `area`, `family`, `scenario_tier` | Entry classification |

The row tags include the dataset, reviewed version, single-turn mode, evaluation scope, and available area/family/tier classifications.

Do not pool different dataset hashes or BCAL package variants as if they were the same population. Rows without package provenance are older/unclassified results, not automatically official or master.

## Compilation evidence in NL2AL scoring

BCal scenario runs persist two separate forms of execution evidence:

- the raw BCal evidence contract remains in each result and is exported unchanged as bc-eval `context`
- a compact `execution_facts` object records only harness-derived scenario, compilation, failure, and execution-identity facts

The stored result `output` remains the exact workspace git diff. For BCal NL2AL rows with normalized execution facts, the bc-eval export wraps that diff in a JSON string containing `authoritative_execution_facts` and `artifact`. This scorer-only envelope makes compilation status visible to the checklist judge without treating BCal's final response or claims inside generated AL as authoritative. Non-BCal rows and older rows without usable evidence keep their existing output unchanged.

Compilation success is taken from the scenario step's `compileSucceeded` value when present. Evidence-only legacy results may use the latest structured `compilation_outcome` event only when the trace is valid and not truncated. BC-Bench never infers compilation success from step completion, completion assessment, stdout/stderr, error text, the agent response, or the generated diff. Missing, malformed, or truncated evidence remains unknown rather than becoming a success or failure claim.

The normalized facts and exported scalar metadata are additive and nullable, so older result JSONL remains loadable and existing non-BCal Kusto rows retain their shape. Raw results produced with scenario evidence can be re-exported and scored under a new run ID; do not overwrite historical Kusto/Braintrust scores. Published bc-eval/Kusto rows are not accepted as raw BC-Bench result JSONL because they no longer contain the typed result identity needed to establish the trust boundary; re-scoring must start from the retained per-instance result artifact. Results created before scenario evidence was recorded cannot be backfilled with compilation facts.

## Complete-panel safety

The BCAL workflow passes the exact selected matrix entry IDs to result summarization. Before any bc-eval export, summarization compares those IDs with the result artifacts and rejects:

- missing result IDs
- unexpected result IDs
- duplicate result IDs

The check is about identity coverage, not score. A valid per-entry timeout or failure result still counts as present.

Every coverage check writes `evaluation_coverage.json`, and the reusable summary workflow uploads it as an artifact even when incomplete coverage blocks scoring. The summary job runs after non-cancelled matrix failures so this diagnostic identifies the missing cases instead of silently skipping the panel-level check.
