# BCAL dataset panels

BC-Bench exposes two reviewed single-turn NL2AL panels for BCAL evaluation:

| Selection | Entries | Purpose |
|---|---:|---|
| `gold` | 110 | Default benchmark panel |
| `challenge` | 65 | Harder held-out panel |

The **Evaluation with bcal** workflow defaults to `gold` for both scheduled and manual runs. Manual runs can select either panel from the `dataset` input. The selected panel is included in the workflow run name, concurrency group, bc-eval run name, and bc-eval tags.

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
| `dataset`, `dataset_version`, `dataset_sha256` | Exact panel identity |
| `dataset_mode` | `single_turn` |
| `dataset_turn_count` | `1` |
| `evaluation_scope` | `single_turn` |
| `area`, `family`, `scenario_tier` | Entry classification |

The row tags include the dataset, reviewed version, single-turn mode, evaluation scope, and available area/family/tier classifications.

## Complete-panel safety

The BCAL workflow passes the exact selected matrix entry IDs to result summarization. Before any bc-eval export, summarization compares those IDs with the result artifacts and rejects:

- missing result IDs
- unexpected result IDs
- duplicate result IDs

The check is about identity coverage, not score. A valid per-entry timeout or failure result still counts as present.

Every coverage check writes `evaluation_coverage.json`, and the reusable summary workflow uploads it as an artifact even when incomplete coverage blocks scoring. The summary job runs after non-cancelled matrix failures so this diagnostic identifies the missing cases instead of silently skipping the panel-level check.
