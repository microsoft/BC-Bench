# Advanced BCal evaluations

`bcal-scenario` and `bcal-feature` share one strongly validated scenario contract:

- `session` configures BCal behavior.
- `steps` contains ordered user turns and optional `plan_action` start/cancel steps.
- `interactions` scripts deterministic answers to matching questions.
- `evaluation` is hidden from BCal and contains compilation, artifact-checklist, trace, forbidden-behavior, and optional runtime requirements.

The harness writes a redacted `execution.json` containing only `schemaVersion`, `session`, `steps`, and `interactions`, then invokes:

```powershell
bcbench evaluate bcal <instance-id> --category bcal-scenario
```

BCal receives `--scenario`, `--result`, and `--exportfolder` arguments. BC-Bench parses `evaluation-run.json` and the archived `chat.json`. A nonzero exit with a step-associated failure and successful export/archive is preserved as a measured agent outcome; missing/invalid results, session-level failures, and export/archive failures are surfaced as harness failures.

Evaluation combines:

1. Deterministic scenario completion and trace assertions.
2. Independent standalone AL compilation when the `al` compiler is installed. If only symbols are available, the result explicitly records `not_attempted`; it is never reported as a successful build.
3. Optional runtime verification (currently `null` in the pilot entries).
4. LMChecklist scoring over the task, confirmed scripted decisions, deterministic summaries, exported workspace diff, and complete textual workspace.

The three original pilot entries cover an inventory-risk feature, an integration-choice interaction, and an explicit plan-first lifecycle.

## Authority/provenance experiment

The `authority-contract` scenarios are a separate deterministic lane for the first narrow system-prompt experiment. They cover:

- direct user scope and an accepted interaction correction;
- declined, cancelled, fallback, and ambiguous replies that leave the workspace unchanged;
- retained direct-user intent after ten intervening history-pressure turns;
- prompt-like AL comments, captions, documentation, diagnostic text, and tool output that cannot broaden scope;
- host profile, page, review, and publish settings that remain facts rather than user authorization.

The fixtures assert changed paths, interaction outcomes, mutation ordering, compilation after the final mutation, and forbidden publishing. LMChecklist still evaluates implementation quality, but it does not determine authority-contract compliance. Ordinary `nl2al` remains a separate category and score.

The harness requests Gate A evidence with BCal's `--include-evidence` option, prefers its canonical trace over the archived chat for tool-order assertions, and preserves execution identity, prompt evidence, trace size, and truncation metadata. Without that explicit opt-in, BCal intentionally omits prompt evidence and canonical trace. Gate B activated-skill evidence is not required for this experiment.

BCal scenario execution uses schema `1.1` and explicitly seeds the generated `app` fixture through workspace-seed contract `1.0` before service creation or the first model request. BC-Bench calculates the contract's privacy-safe, length-prefixed SHA-256 receipt from the exact fixture bytes immediately before invoking BCal and rejects a missing or mismatched returned receipt as a harness failure. The seed includes deterministic `app.json`, `.vscode\launch.json`, and `.vscode\settings.json` bytes, preventing BCal bootstrap generation from creating or changing those files in the exported evidence. Seed receipt count, bytes, and aggregate hash are preserved in result metadata.

The generated `app.json` ID is UUIDv5-derived from the scenario instance ID under the fixed namespace name `https://github.com/microsoft/BC-Bench/bcal-scenario/<instance-id>`. The same case therefore has byte-identical protected bootstrap files and workspace-seed receipts across variants and repetitions.

The checked-in selector is `dataset\experiments\bcal_authority_provenance_v1.json`. It is consumed by `scripts\Run-BCalAuthorityExperiment.ps1` for both baseline and candidate runs. The selector excludes `nl2al__collected-sales-operations-control-tower-1` from every lane because its timeout is investigated separately and is not an authority-contract signal.

Verify the exact baseline and candidate selectors without invoking BCal:

```powershell
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant baseline -Lane authority -OutputDir evaluation_results\baseline -ToolPath <baseline-tool-dir> -DryRun
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant candidate -Lane authority -OutputDir evaluation_results\candidate -ToolPath <candidate-tool-dir> -DryRun
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant baseline -Lane ordinary-quality -OutputDir evaluation_results\baseline -ToolPath <baseline-tool-dir> -DryRun
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant candidate -Lane ordinary-quality -OutputDir evaluation_results\candidate -ToolPath <candidate-tool-dir> -DryRun
```

Remove `-DryRun` to execute a lane locally through the BCal CLI. The runner requires the selector to match `HEAD` and records `selector_git_blob_sha256`, the SHA-256 of the exact bytes returned by `git show HEAD:dataset/experiments/bcal_authority_provenance_v1.json`. This is the checked-in LF blob hash and is stable across checkout line-ending settings; it is not a hash of the platform-specific working-tree file or the generated selection artifact.

The dry-run stdout and persisted `<OutputDir>\selection.json` use the same deterministic serialization: PowerShell `ConvertTo-Json -Depth 8`, LF line endings, one final LF, and UTF-8 without a BOM. An actual run also writes `<OutputDir>\selection.sha256` containing the SHA-256 of those exact `selection.json` bytes. Baseline and candidate selection artifact hashes differ because their `variant` and `package` fields differ; neither replaces `selector_git_blob_sha256`, which identifies the shared checked-in input manifest. The runner also rejects unpublished package entries and a tool directory whose `bcal --version` identity does not exactly match the selected manifest package.

Use the same BC-Bench commit, selector file, datasets, `gpt-55-chat` deployment, backend settings, symbol cache, and two-repeat loop for the candidate. The baseline is the infrastructure-only package `30.0.45.51656-beta` from bic/BC-DeveloperExperience#8982 commit `aca7b2569602e90ea23e0c5f0d866137be3429bc`, build `3000686`. The candidate is `30.0.45.51654-beta` from combined commit `f772a9d1763acc05bb260e0fa885030b0b0cd2eb`, build `3000684`, containing the identical #8982 seed layer plus bic/BC-DeveloperExperience#8977 authority patch `024053c4e6ed7911495de050ec5cb1d2252af07e`. Both builds are final-success and both packages come from `DynamicsSMBTest@Local`. The runner verifies the complete `bcal --version` identity and the retained nupkg SHA-256 before dry-run or execution. Do not reuse the historical unseeded packages and do not use MCP mode.

All GitHub operations for this experiment, including PR inspection, workflow dispatch, run monitoring, and artifact download, must use an authenticated `github.com` account with access to `microsoft/BC-Bench`. Do not use or fall back to a `microsoft.ghe.com` or other GHE account. The runner explicitly checks the `github.com` authentication and repository access before dry-run or execution.

The runner also preflights the accepted external-command backend (`bc-eval==0.6.1`, `src\bcbench\agent\bcal\bc_eval_llm_api_bridge.py`, `BCAL_LLM_MODEL=gpt-55-chat`) and BC 28 symbols under `C:\bcartifacts.cache` before creating a result directory. It does not read, print, or persist backend credentials.

Each case/repetition receives a separate Git workspace and staging result directory under the output directory so Windows file locks or run-directory cleanup from one BCal session cannot affect the next case. After each case completes, the runner collision-checks and copies its result and artifacts into the repetition's aggregate `bcal_test_run` directory. The four per-entry JSONL files therefore remain available at `<OutputDir>\<variant>-authority-rN\bcal_test_run\<instance-id>.jsonl`.

Compare per-entry `trace_compliance` and individual assertion results first, then compilation and scenario completion. Compare LMChecklist scores separately. Promotion scoring uses only IDs in the emitted `selection.json`; the excluded Control Tower timeout is reported separately and never counted as a regression, failure, or denominator. The accepted ordinary-quality reference for `30.0.44.65502-beta` is `103/110` in each of two full gold repetitions from workflow run `40399204122`; rerun baseline and candidate from the same BC-Bench revision before treating a delta as causal.

## Authority experiment result

The final valid seeded3 study used BC-Bench commit `f76d30f3acc15c40915f67112971234e2b42d6fc`:

- baseline workflow run `41801406767`;
- candidate workflow run `41801411108`;
- 8/8 rows completed for each variant (four cases, two repetitions);
- all 16 matched baseline/candidate case-repetition cells had exact workspace-seed parity;
- Gate A evidence, canonical traces, and Kusto result rows were complete;
- the Control Tower case and the ordinary-quality lane were not executed.

Baseline and candidate tied on Core (`2/8`) and LMChecklist judge assertions (`16/24`). Candidate deterministic trace compliance was `5/8`, below baseline `6/8`. The authority prompt change in bic/BC-DeveloperExperience#8977 therefore must not be promoted from this study.

The following studies are infrastructure-invalid and must not be scored or compared:

- `41686175570` / `41686175782`: nullable interaction-choice result-contract incompatibility;
- `41691412171` / `41691423433`: missing Gate A opt-in and empty model-visible workspaces;
- `41798148490` / `41798152826`: random protected `app.json` UUID caused baseline/candidate seed-receipt divergence.
