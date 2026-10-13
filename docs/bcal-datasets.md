# BCAL dataset panels

BC-Bench exposes three reviewed NL2AL panels for BCAL evaluation:

| Selection | Entries | Input | Scoring scope |
|---|---:|---|---|
| `gold` | 110 | One user request | Generated AL/resources |
| `challenge` | 65 | One user request | Generated AL/resources |
| `multiturn` | 7 | Ordered user turns in one BCAL session | Final cumulative artifact |

The **Evaluation with bcal** workflow defaults to `gold` for both scheduled and manual runs. Manual runs can select any panel from the `dataset` input. The selected panel is included in the workflow run name, concurrency group, bc-eval run name, and bc-eval tags.

## BCAL package version

The workflow defaults to `latest-prerelease`, preserving the existing installation behavior. Manual runs can instead select `pinned` and provide an exact NuGet version in `bcal-version`, including an optional fourth numeric component, prerelease suffix, or build metadata. Empty, floating, and range values are rejected before `dotnet` runs.

Every matrix job resolves and installs its own package version. The installer reads the structured global-tool list after installation and passes the verified actual NuGet version to evaluation. Raw results record that observed value as `agent_version`, including agent failures and timeouts; they never record `latest`, `unknown`, or an unchecked requested string. Because a feed can publish between matrix jobs, use a pinned version when every case must run with the same package.

Local `evaluate bcal` performs the same global-tool discovery. Use `--bcal-version <exact-version>` or set `BCAL_PACKAGE_VERSION` to require the installed version to match an expected value:

```powershell
uv run bcbench evaluate bcal <instance-id> --dataset gold --bcal-version 18.0.38.47039-beta
```

## Local usage

```powershell
uv run bcbench dataset list --category nl2al --dataset gold
uv run bcbench dataset list --category nl2al --dataset challenge
uv run bcbench dataset list --category nl2al --dataset multiturn
uv run bcbench dataset view <instance-id> --category nl2al --dataset multiturn
uv run bcbench dataset version <instance-id> --category nl2al --dataset multiturn

# Generation only
uv run bcbench run bcal <instance-id> --dataset multiturn

# Generation plus raw evaluation result
uv run bcbench evaluate bcal <instance-id> --dataset multiturn

# Validate and summarize a completed run
uv run bcbench result summarize --run-id <run-id> --category nl2al --dataset multiturn
```

`run bcal` and `evaluate bcal` isolate generated source under `<repo-path>\<instance-id>\workspace`, so one entry does not reset another entry's workspace or its diagnostics.

`dataset version` writes both the Business Central version and the exact selected JSONL path when `--github-output` is used. The workflow passes that path to symbol resolution, so an entry is never resolved against a different panel.

## Multi-turn execution and evidence boundary

A multi-turn entry contains authored user messages and per-customization artifact checkpoints. BCAL executes all turns in one native `--scenario` / `--result` invocation, preserving one session and workspace. The runner never flattens the conversation into one prompt or starts a process per turn.

Before invoking the model, the runner probes `bcal --help` and requires both native options. Each scripted customization step must succeed, report successful compilation, and appear in the authored order. The final result must also report consistent totals, no clarification interactions, a successful export, and a successful session archive.

The native protocol exports the final workspace. Evaluation therefore scores the cumulative artifact checklist from the final customization checkpoint after all scripted turns complete. Earlier requirements that were explicitly withdrawn are not required again. This does not claim evidence for intermediate filesystem snapshots, deployed behavior, UI interaction, or business-record changes.

The seven selectable conversations contain customization turns only. Seven additional conversations remain in `dataset\nl2al_multiturn_pending.jsonl` because they require reviewed active-page context or explicit interaction mappings for plan, inspect, or clarification turns. The runner rejects these mixed conversations rather than fabricating answers.

Scenario input, native result data, session archives, and stdout/stderr are stored outside the generated AL workspace in a unique directory per invocation. GitHub Actions uploads these `bcal-scenario` diagnostics separately from result JSONL artifacts, so stale scenario output cannot mask a failed rerun and diagnostic JSON is not scored.

## Identity and scoring provenance

Every named-panel raw result records:

- `dataset`: `gold`, `challenge`, or `multiturn`
- `dataset_version`: the reviewed dataset revision from `dataset/nl2al_manifest.json`
- `dataset_sha256`: the exact SHA-256 of the selected JSONL at evaluation time

Summarization loads prompts, ordered turns, and expected assertions from that same panel. It refuses to export results when the requested panel differs from the recorded panel, a named-panel result lacks identity, the JSONL hash changed, the recorded dataset version is wrong, the result ID is absent from the selected panel, or the selected panel contains the wrong turn structure.

Older results without panel identity keep their legacy behavior when summarization does not name a panel. They are not automatically labeled as gold.

Each named-panel bc-eval row includes:

| Metadata | Value |
|---|---|
| `dataset`, `dataset_version`, `dataset_sha256` | Exact panel identity |
| `dataset_mode` | `single_turn` or `multiturn` |
| `dataset_turn_count` | `1` or the authored turn count |
| `evaluation_scope` | `single_turn` or `final_artifact` |
| `area`, `family`, `scenario_tier` | Entry classification |

For multi-turn rows, the exported task input preserves the authored turn order and intents, while the expected output is the final customization checkpoint. Row tags include the dataset, reviewed version, dataset mode, evaluation scope, and available area/family/tier classifications.

## Complete-panel safety

The BCAL workflow passes the exact selected matrix entry IDs to result summarization. Before any bc-eval export, summarization compares those IDs with the result artifacts and rejects:

- missing result IDs
- unexpected result IDs
- duplicate result IDs

The check is about identity coverage, not score. A valid per-entry timeout or failure result still counts as present.

Every coverage check writes `evaluation_coverage.json`, and the reusable summary workflow uploads it as an artifact even when incomplete coverage blocks scoring. The summary job runs after non-cancelled matrix failures so this diagnostic identifies the missing cases instead of silently skipping the panel-level check.
