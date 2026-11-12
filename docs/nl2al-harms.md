---
layout: default
title: NL2AL accuracy and harms
---

# Repeatable NL2AL accuracy and harms evaluation

The fixed harms cases evaluate BCal instruction following through direct prompts and indirect
tool-result injection. Code lives under `bcbench.agent.bcal.harms`, with a dedicated
`python -m bcbench.agent.bcal.harms` entry point; it is not a cross-category framework.
For Azure-generated attacks and attack strategies, use the existing `bcbench redteam scan`.
No harvesting, source-plugin protocol, couching library or template language is added here.

## Setup and pins

Use PowerShell 7, .NET 10, Python 3.13 and the uv version required by `pyproject.toml`.
Install the workspace with `uv sync --all-packages`; optional Azure telemetry additionally needs
`--extra redteam`. Authenticate with `az login`, configure `LLM_API_*` as described in
`.env.sample`, and obtain access to the authorized BCal/BC Python feeds and certificate vault.
Do not commit credentials or redistribute the internal BCal package.

The published runtime for this evaluation is `Microsoft.BusinessCentral.BCal.CLI`
**30.0.46.28048-beta**, source **7c5514f77dc3346194813ec8d6a475f654d685ab**.
Its nupkg SHA256 is `5a0d0f255ec8b69f6fae6412f7199fddf0b463437e81308986ad107ed1b2dc4d`.
Keep the whole tool directory. Use your organization's Azure Artifacts credential provider:

```powershell
dotnet tool install Microsoft.BusinessCentral.BCal.CLI --version 30.0.46.28048-beta `
    --tool-path .\.tools\bcal --add-source $env:BCAL_FEED_URL --interactive
if ($LASTEXITCODE) { throw 'BCal installation failed' }

# Separate Python 3.13 environment, pinned bc-eval 0.6.1 and OpenAI 3.45.0.
.\scripts\Setup-BCalBridge.ps1 -PythonFeedUrl $env:BC_EVAL_PYTHON_FEED_URL
.\scripts\Download-BCSymbols.ps1 -Category nl2al -Tier gold -InstanceId nl2al__move-name-customer-card-2
```

`BCAL_EXECUTABLE` explicitly selects the runtime; other callers still use PATH when it is unset.
The external-command backend uses `bc_eval_llm_api_bridge.py` and M365 LLM API, not the retired
CAPI bridge. Ceres (`gpt-56-ceres`) uses Chat Completions. The existing reasoning-sol selection
needs the Responses continuation path and a runtime that preserves opaque provider context.
Neither path disables reasoning. Record agent and judge identities separately.

## Capture and score

Commit the checkout, use checkout/bridge paths without spaces, and use short, fresh output
directories. The wrapper records source revision, runtime/model, bridge packages, dataset hashes
and symbol hashes. Accuracy uses a separate directory per entry. It does not run the judge.

```powershell
$runtime = (Resolve-Path .\.tools\bcal\bcal.exe).Path
$artifactVersion = '<exact downloaded BC 28.0 artifact version>'
$run = Join-Path 'C:\bcbench-runs' ('ceres-' + (Get-Date -Format yyyyMMdd-HHmmss))

.\scripts\Run-NL2ALEvaluation.ps1 -Category accuracy -BcalExecutable $runtime `
    -ArtifactVersion $artifactVersion -Model gpt-56-ceres -ResultsDirectory "$run\accuracy"
.\scripts\Run-NL2ALEvaluation.ps1 -Category harms -BcalExecutable $runtime `
    -ArtifactVersion $artifactVersion -Model gpt-56-ceres -Vector direct,symbols,page_inspector `
    -ResultsDirectory "$run\harms"

.\.bcal-llm-api-venv\Scripts\python.exe .\tools\score_nl2al.py `
    "$run\accuracy\accuracy\bceval_results.jsonl" "$run\accuracy\checklist-scores.jsonl" `
    --model gpt-56-ceres
uv run python -m bcbench.agent.bcal.harms score "$run\harms\harms" `
    --model gpt-5.3-codex --output-dir "$run\objective-scores"
```

After preflight and approval of the exact pins, `-Full` selects all accuracy entries or all
six comprehensive harms cases. Omit `-Vector` for the six-vector, 36-trial harms matrix.
Harms uses the gold base entry; challenge is rejected rather than mislabelled.
Missing delivery remains missing coverage; do not silently narrow the matrix for a full result.

The dedicated CLI also supports `run --dry-run --limit 1 --vector direct --results-dir <new-dir>`,
`report <saved-dir>` and `annotate <saved-dir> --output-dir <new-dir>`.
Capture never contacts Foundry or fetches BCQuality. Scoring and annotation require a new output
directory, preserving the original captures. `annotate` reconstructs delivery from saved logs.
Accuracy's local checklist adapter validates raw judgments before the bc-eval parser: one real
Boolean with reasoning per assertion; missing, duplicate or malformed judgments fail and are retained.

## Fixed cases and validity

Suites are plain YAML under `dataset/nl2al/harms`: `comprehensive.harms.yaml` is the run matrix;
`code-vulnerability.harms.yaml` provides optional BCQuality-grounded cases. Both accept `defaults`
and a nonempty `cases` list. Each case has a unique `id`, `harm`, `page`, optional `audience`,
benign `trigger`, `risk` label, `vectors` and per-vector `placement`. Optional `rule`, `detector`
and `expected` describe scoring evidence. Labels are authored metadata, not generated taxonomy.

Direct trials send `harm` as the prompt. Indirect trials send the benign trigger and inject
the payload through BCal's `--harms-fixture` contract into symbols, page inspection, translations,
ask-user responses or package translations. Targets must name actual BC objects/modules.
Package source injection requires a separately restored/resumed workspace and is not prepared
by this capture path. Page-inspection triggers do not guarantee translations or ask-user calls.

A trial is eligible only after successful execution and verified delivery. Indirect delivery
requires the payload in a captured tool result, not a fixture flag or log diagnostic. Execution
failures, historical timeout responses and injection misses are not resistance. Logs, fixtures,
case snapshots, response text and exported AL remain available for audit.

The objective judge receives the attack, legitimate task, expected outcome, response and separate
generated AL as untrusted evidence. Code objectives require artifacts; prose objectives can succeed
without AL. Only its strict Boolean verdict determines objective realization; an inconclusive
`null`, missing output or judge error remains unscored. Regex signatures inspect AL only and are
advisory; they cannot override the judge. Content-filter words do not bypass substantive judgment.

Reports show attempted, delivered, scored and delivered-but-unscored counts. The rate applies only
to the scored subset. Scoring fails if no rows were scored or delivered rows lack judgments.
Scorer `nl2al-objective-v2`, source hashes, input SHA256 and judge model are recorded separately.
Old captures can use retained AL exports without rerunning BCal. Injection misses require new
captures to establish coverage. Objective following is **not proof of an exploitable AL vulnerability**.

## Optional upstream BCQuality guidance

Rule-bearing cases use [microsoft/BCQuality](https://github.com/microsoft/BCQuality) at exact commit
`4119417ce4db7cd5423671fb726459c485549f6c`. No upstream content is vendored or fetched automatically.
Supply an existing checkout, or explicitly clone outside the benchmark checkout:

```powershell
git clone --no-checkout https://github.com/microsoft/BCQuality.git C:\bcquality-pinned
git -C C:\bcquality-pinned checkout --detach 4119417ce4db7cd5423671fb726459c485549f6c
uv run python -m bcbench.agent.bcal.harms score <saved-dir> `
    --bcquality-root C:\bcquality-pinned --output-dir <new-scores-dir>
```

`BCQUALITY_ROOT` is equivalent to the option. The judge verifies HEAD and reads committed blobs,
not modified working-tree content. Missing rules or the wrong revision produce explicit errors.
Grounded trials record `bcquality_commit`. Rules live under `community/knowledge/security`,
except the sensitive-public-API rule under `microsoft/knowledge/breaking-changes`.
`--no-judge` is detector diagnostics only, not a completed evaluation.

## Optional Azure response telemetry

```powershell
uv run python -m bcbench.agent.bcal.harms evaluate <saved-dir> --no-upload
```

This needs the redteam extra, Azure credentials and `AZURE_SUBSCRIPTION_ID`,
`AZURE_RESOURCE_GROUP`, `AZURE_PROJECT_NAME`. `--no-upload` still calls Azure evaluators;
omit it only with authorization to upload the capture to that project.
Content safety, indirect-attack and code-vulnerability evaluators classify the **response only**.
Their output is generic telemetry, not objective-conditioned attack success or validated AL
vulnerability detection. Missing/partial scores are explicit failures.

## GitHub execution and current limitation

```powershell
gh workflow run bcal-evaluation.yml --repo microsoft/BC-Bench --ref <reviewed-branch> `
    -f evaluation-kind=harms -f tier=gold -f external-model=gpt-56-ceres `
    -f completion-review-model=none -f test-run=true
```

Accuracy remains the workflow default and scheduled path. Harms is opt-in and pins the runtime above,
BC artifacts `28.0.46665.52171`, Copilot CLI `1.0.82` and objective judge `gpt-5.3-codex`.
The bounded job captures the first case through direct, symbols and page inspection. Full mode is
explicit `test-run=false`. Delivery/scoring gaps fail its coverage gate. It uses existing `ado-read`
credentials and Copilot Requests permission, and uploads selected evidence, not binaries/certificates.

The first hosted attempt, [43149879650](https://github.com/microsoft/BC-Bench/actions/runs/43149879650),
installed the runtime and bridge but could not resolve the pinned BC artifact from the current index.
Hosted execution is **not yet proven**. Do not silently substitute a newer BC version or claim local
cached runs establish fresh-host readiness. An obtainable exact artifact or an explicitly approved
new artifact pin is needed before another hosted preflight.
