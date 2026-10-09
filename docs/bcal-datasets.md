# BCAL dataset panels

The **Evaluation with bcal** workflow has a `dataset` dropdown:

| Selection | Entries | Input | Scoring scope |
|---|---:|---|---|
| `gold` (default) | 110 | One user request | Generated AL/resources |
| `challenge` | 65 | One user request | Generated AL/resources |
| `multiturn` | 7 | Ordered user turns in one BCAL session | Final cumulative artifact |

The scheduled run uses gold. A manual test run samples four entries and does not upload to Kusto/Braintrust. Uncheck `test-run` for a full panel and storage upload. Dataset identity is included in the workflow run name and concurrency group.

The workflow also offers `bcal-version-mode`: **latest-prerelease** (the default, preserving the existing prerelease install) or **pinned**. For pinned mode, enter the exact NuGet version in `bcal-version`, including any fourth numeric component or prerelease suffix. A floating version/range is not an exact pin. GitHub's dropdown cannot dynamically enumerate the private feed's versions, so the pin is a separate text input.

Each matrix job installs latest independently, preserving the existing behavior, or installs the exact requested pin. The job records its **actual installed** package version from `dotnet tool list --global --format json`, not the word "latest" or an assembly/file version. Evaluation verifies the observation before starting and persists it as `agent_version`, including timeout/failure results. Local `evaluate bcal` discovers the same global NuGet tool; `--bcal-version` / `BCAL_PACKAGE_VERSION` can supply an expected version to verify, not an unchecked replacement value. If the feed changes during a latest run, different cases may record different versions; use the exact pin when a uniform version is desired.

These are reviewed **candidate** datasets, not measured RAI qualification. The gold panel remains above 100 single-shot cases. A separate 95% whole-case qualification would require 105/110 passing cases, complete grading/execution evidence and the applicable safety review; the native aggregate LMChecklist score is not that gate.

## Local usage

```powershell
uv run bcbench dataset list --category nl2al --dataset gold
uv run bcbench dataset list --category nl2al --dataset challenge
uv run bcbench dataset list --category nl2al --dataset multiturn
uv run bcbench dataset view nl2al__collected-mt-continuity-note-undo-1 --category nl2al --dataset multiturn

# Use the normal approved external-command LLM bridge configuration.
uv run bcbench evaluate bcal nl2al__add-industry-field-customer-card-2 --dataset gold
uv run bcbench evaluate bcal nl2al__collected-mt-continuity-note-undo-1 --dataset multiturn
uv run bcbench result summarize --run-id <run-id> --category nl2al --dataset multiturn
```

`run bcal` supports the same selector for generation without result scoring. Its workspace, like `evaluate bcal`, is isolated under `<repo-path>\<instance-id>\workspace`; one entry does not reset the whole result directory.

The selector also applies to `dataset version`, so downloading symbols uses the selected panel rather than silently searching gold. Non-NL2AL categories do not accept these panels.

## Multi-turn execution and evidence boundary

A multi-turn entry contains real user messages and per-turn artifact requirements, not canned assistant responses. BCAL executes them in **one** native `--scenario` schema-1.0 call. It never flattens them into a single prompt or starts a new process for every follow-up. The installed BCAL CLI must support that protocol; an older or failing CLI is an execution failure, not a simulated conversation.

The scenario sets `publish=never`, requests review, and cancels unexpected clarification prompts. The same workspace and conversational state are retained within the scenario. Execution metadata is saved separately under `bcal-scenario` and uploaded as a debugging artifact, not mixed into generated AL or bc-eval result inputs.

The native protocol exports a **final** workspace. Consequently this workflow scores the cumulative artifact checklist from the **last customization turn**, after all scripted turns have run. Earlier requirements that were explicitly withdrawn are not incorrectly required again. It does not claim to score intermediate filesystem snapshots, every interaction, actual UI behavior, business-record persistence or deployment.

Seven mixed plan/clarification/inspection conversations are retained in `dataset\nl2al_multiturn_pending.jsonl`, but are not selectable yet. BCAL's synchronous `ask_user` cannot consume a later scripted user turn automatically, and routing metadata must not supply a page where the case requires no active-page context. These cases need explicit, reviewed interaction/context mappings rather than canceled clarifications or fabricated answers. The seven runnable cases are the local bundle's native scenario index.

Four interaction-only conversations from the local curation bundle are intentionally not included: no generated AL is their correct outcome, and this pipeline evaluates AL artifacts. Full SEVAL data, diagnostic variants, private source snapshots and research notes are not published here.

## Kusto identity

The suite remains `nl2al`, and `EvalRunType` retains its existing baseline/experiment meaning. Selecting a different dataset is not an agent customization experiment.

The run name ends with `[gold]`, `[challenge]` or `[multiturn]`, with a corresponding `dataset-gold`, `dataset-challenge` or `dataset-multiturn` run tag. Each exported bc-eval record also includes:

| Metadata field | Meaning |
|---|---|
| `model` | AL-generation model selected for the BCAL external-command bridge |
| `judge_model` | LMChecklist judge model, independent of the generation model |
| `agent_version` | Actual installed BCAL NuGet package version, preserving prerelease suffixes |
| `dataset` | Selected panel |
| `dataset_version` | Reviewed dataset revision |
| `dataset_sha256` | Hash of the selected repository JSONL |
| `dataset_mode` | `single_turn` or `multiturn` |
| `dataset_turn_count` | Authored user turns in the entry |
| `evaluation_scope` | `single_turn` or `final_artifact` |
| `area`, `family`, `scenario_tier` | Case categorization; multi-turn preserves gold/challenge source tier |

Dataset identity is persisted in raw results, including timeouts and failures. Summarization verifies the requested panel and recorded file hash before choosing assertions. It refuses mismatched datasets instead of dropping the case or scoring it against gold.

Example filter against the existing result table:

```kusto
AIEvalResults
| where FeatureName == "BC-Bench" and EvalSuiteName == "nl2al"
| where EvalRunName startswith "BCal"
| where tostring(Metadata.dataset) == "challenge"
| project Timestamp, EvalRunId, EvalResultId, CoreScore,
    GenerationModel = tostring(Metadata.model),
    ChecklistModel = tostring(Metadata.judge_model),
    BcalPackageVersion = tostring(Metadata.agent_version),
    Dataset = tostring(Metadata.dataset),
    DatasetVersion = tostring(Metadata.dataset_version),
    Scope = tostring(Metadata.evaluation_scope)
```

Do not pool single-turn and final-artifact multi-turn scores, or different dataset hashes, as if they were the same population. Rows without dataset metadata are older/unclassified results, not automatically gold.

For older runs without `agent_version`, the GitHub Actions **Install bcal CLI from internal feed** log may show the version installed. Do not infer it from today's installed package or today's newest feed version, and do not backfill an unobserved value into historical results.

To see all recorded model/package combinations for a run:

```kusto
AIEvalResults
| where FeatureName == "BC-Bench" and EvalSuiteName == "nl2al"
| where EvalRunId == "<run-id>"
| summarize GenerationModels = make_set(tostring(Metadata.model)),
    ChecklistModels = make_set(tostring(Metadata.judge_model)),
    BcalPackageVersions = make_set(tostring(Metadata.agent_version)),
    Datasets = make_set(tostring(Metadata.dataset))
```

## Dataset maintenance

`dataset\nl2al_manifest.json` records counts, source canonical hash and exported-file hashes. The import tool takes a reviewed local bundle and writes only publishable BC-Bench panels:

```powershell
uv run python tools\import_nl2al_bundle.py <local-reviewed-bundle>
```

The underlying candidate-v2 collection has 110 gold single-shot cases, 65 challenge single-shot cases and 14 functional conversations, of which seven currently qualify for native scripted execution. It was expanded with 32 distinct designed cases rather than padding gold with diagnostic variants. Prompts and intended final checks are preserved; internal source attribution is deliberately not imported. Dataset/evaluation changes use a new benchmark major version under the repository versioning policy.
