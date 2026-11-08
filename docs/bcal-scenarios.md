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

The fixtures assert changed paths, interaction outcomes, mutation ordering, compilation after the final mutation, forbidden publishing, and exact hidden artifact content. The exact artifact checks preserve object IDs and reject wrong return values, unrelated edits, unchanged broken source, or changes to evidence-only files without exposing expected content to BCal. LMChecklist still evaluates implementation quality, but it does not determine authority-contract compliance. Ordinary `nl2al` remains a separate category and score.

The harness requests Gate A evidence with BCal's `--include-evidence` option, prefers its canonical trace over the archived chat for tool-order assertions, and preserves execution identity, prompt evidence, trace size, and truncation metadata. Tool-event assertions fail closed when the canonical trace is truncated or reports omitted events; incomplete evidence cannot prove required/forbidden tool use or ordering. Without that explicit opt-in, BCal intentionally omits prompt evidence and canonical trace. Gate B activated-skill evidence is not required for this experiment.

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

Use the same BC-Bench commit, selector file, datasets, `gpt-55-chat` deployment, backend settings, symbol cache, and two-repeat loop for paired experiments. The current baseline calibration pin is the immutable merged-master package `30.0.45.61801-beta`, ProductVersion `30.0.45.61801+1376d89652f8ca366dcf1f6fb0e1a43f671ec046`, IntegrationValidation build `3010831`, package SHA-256 `15ef20feeba483f7d6f0f3959534aa3b91cdcec8dd597554539be959c7fc279f`, with no authority prompt patch. The historical candidate package remains recorded only for the seeded3 study and must not be dispatched for baseline calibration. The runner verifies the complete `bcal --version` identity and retained nupkg SHA-256 before dry-run or execution. Do not use MCP mode.

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

### Post-seeded3 calibration

The seeded3 postmortem identified three suite defects rather than prompt effects:

- the direct/corrected-scope interaction matcher required `Customer` or `Vendor` in the question text even when the alternatives appeared only in structured choices;
- the old missing-semicolon fixture compiled unchanged, so it did not measure syntax repair;
- judge wording alone could not prove that the intended object and only the intended bytes were preserved.

The repaired matcher identifies the scope/target decision from question text and validates `Customer`/`Vendor` through the structured choices. The untrusted-evidence fixture now contains `exit('fixed';`, which the AL compiler rejects with `AL0104` until the exact one-character parenthesis repair is applied. Hidden exact-content assertions preserve object IDs `50102` and `50103`, require the intended return/syntax edits, and keep the evidence-only README, symbol metadata, and tool-output files unchanged. Interaction diagnostics now distinguish a missing `ask_user` call from an observed call that failed scripted matching or acceptance.

The baseline-only calibration study is `bcal-authority-calibration-20261105/baseline`, common-base `1376d89652f8ca366dcf1f6fb0e1a43f671ec046`, variant patch `no-patch`, four authority cases, and two repetitions. It is not a prompt-promotion study and must not run a candidate, Control Tower, or ordinary-quality lane.

The authorized baseline workflow run `42080222103` is infrastructure-invalid and does not calibrate scenario semantics. All eight case/repetition jobs produced artifacts with matching seed receipts, Gate A prompt evidence, and nontruncated canonical traces, but every first model request failed before a response with `LLM API: Required taxonomy data x-sticky-route-session-ticket not provided`. Publication-only retries `42083481136`, `42083866657`, and `42084260667` could not obtain LMChecklist judge results. The final retry published eight diagnostic Kusto rows with null Core scores and no judge scores; their zero deterministic rates reflect the pre-model backend failure and must not be interpreted as scenario outcomes. The repaired suite remains unfrozen until the accepted external-command backend can complete a fresh four-case by two-repetition baseline calibration with complete judge and Kusto evidence.

The authoritative LLM API metadata contract requires `x-sticky-route-session-ticket` on every request: send an empty value on the first request, then cache and replay the opaque response ticket per session and model, defaulting a missing response ticket back to empty. Because BCal starts a fresh external-command process for each turn and its wire request contains no session identifier or routing metadata, BC-Bench owns an authenticated in-memory broker for the lifetime of each BCal run. Bridge processes exchange tickets only with that broker; tickets are never written to the workspace, result directory, benchmark artifacts, stdout, stderr, or logs. Direct bridge invocation without the session broker fails explicitly. The judge path retains the same in-process per-client cache. The real-backend preflight now makes two separate external-command process calls so the second turn exercises opaque ticket replay, in addition to the `gpt-56-ceres` judge request.

Calibration run `42088019953`, study/ref `bcal-authority-calibration-sticky1-20261105`, is also infrastructure-invalid for suite calibration. All eight model cells completed with exact artifacts, seed parity, prompt evidence, nontruncated traces, and Kusto publication, but the direct-scope ordering assertion recognized only `write_file` while the canonical tool was `edit_file`. Commit `ecc7e0bdcb33438c399210ef8e7c84cdf64161b8` makes tool-order assertions treat all recognized edit/write tools as semantic workspace mutations.

The final baseline-only calibration is run `42091595469`, immutable tag/study `bcal-authority-calibration-sticky2-20261105`, commit `b35d9bd873ee7326a4e268a1ad3b2b71e1ed4355`. Its selector Git-blob SHA-256 is `e39263b4b8154c590dc47a3c57c9f725430ac2d76cd6ac883e38fb9ac7cff625`; canonical selection SHA-256 is `900ba57534b6e6e6426920bbcdd4df2ccfb21448b5e52241ce84664a785db01b`. GitHub and Kusto duplicate gates were zero before dispatch. Exactly four repaired authority cases ran twice; no candidate, Control Tower, or ordinary lane ran. All eight cells completed with one identical seed aggregate per case across repetitions, complete prompt evidence, nontruncated canonical traces, no harness failures, deterministic trace compliance `8/8`, Core `8/8`, and LMChecklist critical pass rate `8/8`. Kusto contains eight rows across two repetition run IDs with no errors. The repaired authority suite is frozen and ready for future paired experiments; this baseline-only calibration makes no prompt-promotion decision.

The following studies are infrastructure-invalid and must not be scored or compared:

- `41686175570` / `41686175782`: nullable interaction-choice result-contract incompatibility;
- `41691412171` / `41691423433`: missing Gate A opt-in and empty model-visible workspaces;
- `41798148490` / `41798152826`: random protected `app.json` UUID caused baseline/candidate seed-receipt divergence.

## Report skill progressive-disclosure study

The package-independent report-authoring cohort is checked in as
`dataset\experiments\bcal_report_skill_progressive_disclosure_v1.json`. It
selects exactly six `bcal-scenario` entries covering report creation,
extension/repair, output-mode choice, labels and filters, source clarification,
and one larger Sales Order analysis report. Every entry requires compilation,
deterministic artifact checks, and a nonpublishing trace. Workspace seeds,
model, package, cases, and two repetitions are shared across all three variants:

- permanent full report guidance;
- model-triggered report skill;
- deterministic host-triggered report skill.

Skill variants require Gate B delivery from the configured source before the
first workspace mutation. The permanent-guidance variant rejects report-skill
delivery. All report-study variants reject a missing or truncated canonical
trace. Pre-model failures remain coverage rows but set
`semantic_metrics_eligible=false`, so semantic comparisons must filter them out.

The authorized immutable study is
`bcal-report-skill-progressive-disclosure-20261108`. The selector records the
original #1011 starting SHA as provenance and pins repaired #1011 head
`1969363374c57aa23bb79ea0f3ec537ce440c870`, which makes truncated or omitted
canonical tool traces fail closed and preserves sticky-route tickets in an
authenticated in-memory per-run broker across separate bridge processes. It
pins `gpt-55-chat`, all three package byte identities, and the
`report-authoring` 1.0.0 content/revision/catalog/activated-segment identity.
The immutable study version of the registered `bcal-evaluation.yml` workflow reads those values
from the selector and runs one six-case repetition per dispatch. Exactly six
dispatches (three variants by two repetitions) produce the authorized 36 cells.

Validate the package-independent cohort without invoking BCal:

```powershell
.\scripts\Run-BCalReportSkillExperiment.ps1 `
  -Variant permanent-full-report-guidance `
  -ValidateCohort
```

Execution requires the immutable study ref, exact matching BCal ProductVersion
and nupkg bytes, the fixed bridge/model, BC 28 symbols, complete six-row
coverage, and noncolliding GitHub/Kusto study provenance. Gate B verifies the
skill contract, content SHA, revision, catalog and activated segments,
activation mode, requested-tool-call ID nullability, complete canonical trace,
and delivery before the first workspace mutation. The permanent-guidance
variant rejects activated-skill delivery. Control Tower, unrelated lanes,
replacement candidates, and semantic retries are prohibited.
