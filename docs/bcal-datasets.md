# BCAL evaluation

## Dataset tiers

Single-turn NL2AL entries live in two files: `dataset/nl2al.jsonl` is the `gold` benchmark set (default) and `dataset/nl2al_challenge.jsonl` is the harder held-out `challenge` set. NL2AL is currently the only category with a challenge set.

The **Evaluation with bcal** workflow evaluates `gold` by default; manual runs can pick a tier from the `tier` input. The tier is part of the workflow run name, concurrency group, and bc-eval run name and tags, and every raw result and bc-eval row records it.

Every command that loads entries accepts the same option:

```powershell
uv run bcbench dataset list --category nl2al --tier challenge
uv run bcbench run bcal <instance-id> --tier challenge
uv run bcbench evaluate bcal <instance-id> --tier challenge
```

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
uv run bcbench evaluate bcal <instance-id> --bcal-version 18.0.38.47039-beta
```

## bc-eval metadata

Each bc-eval row includes:

| Metadata | Value |
|---|---|
| `agent_version` | Actual installed BCAL NuGet package version |
| `bcal_package_source` | `official` or `experiment` |
| `bcal_package_branch` | `master` or the provenance-derived BC-DeveloperExperience source branch |
| `bcal_package_feed` | `DynamicsSMBPackages` or `DynamicsSMBTest@Local` |

Do not pool different BCAL package variants as if they were the same population. Rows without package provenance are older/unclassified results, not automatically official or master.
