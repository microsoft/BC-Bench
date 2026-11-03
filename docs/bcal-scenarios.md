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

The checked-in selector is `dataset\experiments\bcal_authority_provenance_v1.json`. It is consumed by `scripts\Run-BCalAuthorityExperiment.ps1` for both baseline and candidate runs. The selector excludes `nl2al__collected-sales-operations-control-tower-1` from every lane because its timeout is investigated separately and is not an authority-contract signal.

Verify the exact baseline and candidate selectors without invoking BCal:

```powershell
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant baseline -Lane authority -OutputDir evaluation_results\baseline -ToolPath <baseline-tool-dir> -DryRun
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant candidate -Lane authority -OutputDir evaluation_results\candidate -ToolPath <candidate-tool-dir> -DryRun
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant baseline -Lane ordinary-quality -OutputDir evaluation_results\baseline -ToolPath <baseline-tool-dir> -DryRun
.\scripts\Run-BCalAuthorityExperiment.ps1 -Variant candidate -Lane ordinary-quality -OutputDir evaluation_results\candidate -ToolPath <candidate-tool-dir> -DryRun
```

Remove `-DryRun` to execute a lane locally through the BCal CLI. The runner rejects a tool directory whose `bcal --version` identity does not exactly match the selected manifest package. Each run writes `selection.json` with the selector hash, exact package identity, selected IDs, promotion IDs, exclusions, variant, lane, and repeat count before evaluation starts.

Use the same BC-Bench commit, selector file, datasets, `gpt-55-chat` deployment, backend settings, symbol cache, and two-repeat loop for the candidate. Pin the baseline package to `30.0.44.65502-beta`; pin the candidate to its exact package version. Do not use MCP mode.

All GitHub operations for this experiment, including PR inspection, workflow dispatch, run monitoring, and artifact download, must use an authenticated `github.com` account with access to `microsoft/BC-Bench`. Do not use or fall back to a `microsoft.ghe.com` or other GHE account. The runner explicitly checks the `github.com` authentication and repository access before dry-run or execution.

The runner also preflights the accepted external-command backend (`bc-eval==0.6.1`, `src\bcbench\agent\bcal\bc_eval_llm_api_bridge.py`, `BCAL_LLM_MODEL=gpt-55-chat`) and BC 28 symbols under `C:\bcartifacts.cache` before creating a result directory. It does not read, print, or persist backend credentials.

Each case/repetition receives a separate Git workspace and staging result directory under the output directory so Windows file locks or run-directory cleanup from one BCal session cannot affect the next case. After each case completes, the runner collision-checks and copies its result and artifacts into the repetition's aggregate `bcal_test_run` directory. The four per-entry JSONL files therefore remain available at `<OutputDir>\<variant>-authority-rN\bcal_test_run\<instance-id>.jsonl`.

Compare per-entry `trace_compliance` and individual assertion results first, then compilation and scenario completion. Compare LMChecklist scores separately. Promotion scoring uses only IDs in the emitted `selection.json`; the excluded Control Tower timeout is reported separately and never counted as a regression, failure, or denominator. The accepted ordinary-quality reference for `30.0.44.65502-beta` is `103/110` in each of two full gold repetitions from workflow run `40399204122`; rerun baseline and candidate from the same BC-Bench revision before treating a delta as causal.
