---
layout: default
title: Code Review - BC-Bench
---

<style>
  /* Widen this page so the leaderboard table breathes instead of cramming into the narrow column */
  .main-content {
    max-width: 80rem;
  }
  .main-content table {
    display: table;
    width: 100%;
    table-layout: auto;
  }
  .main-content table th,
  .main-content table td {
    padding: 0.4rem 0.6rem;
  }
</style>

# Code Review

This category evaluates an agent's ability to **review** a Business Central (AL) pull request. Given a diff, the agent produces structured review comments, which are scored against an expected (gold) set of findings.

Unlike the pass/fail categories, code review is scored with **Precision / Recall / F1** using the explicit `any-match` policy. Precision counts **generated comments** with at least one confirmed positive match; recall counts **unique required gold issues** covered. One comment covering three issues earns one precision TP and three covered golds. Two duplicate comments covering one issue earn two comment TPs but cover only one gold. Thus recall is `covered_gold_count / expected_comment_count`, not comment TP divided by TP plus FN.

A gold entry may also declare **`ignored_comments`** — legitimate-but-optional observations that should be neither required nor penalized. Every same-file expected/ignored/generated pair is judged independently in one pass using the fixed judge model, before any assignment. Any positive match takes precedence over neutral matches. Every neutral-only output is excluded from precision, including duplicates; it earns no recall. Unmatched output counts against **gold-relative matched-comment precision**, not an independently established factual-error rate: missing gold remains possible.

The user accepts optimistic comment-level precision: one specific correct positive part suffices even if other claims are incorrect or unverified. We do not split generated claims or certify whole-comment correctness. Gold should represent one independent repair obligation, not separate cause/impact/remedy or repeated descriptions. No benchmark gold was split for this change: performance-001's proposed extra projection gold remains unapproved because applicability/severity are unresolved. `redundant_matched_comment_count` records outputs adding no new gold coverage in generated order; it is a coverage-noise diagnostic, not a semantic duplicate adjudication.

Matching retains the existing normalized same-file hard gate, without line-distance cutoff, nearest-only selection or top-k pruning. Protocol `specific-site-v2` supplies both line ranges and the full fixture diff as a JSON string whose escaped newlines survive CLI argument flattening. The judge must establish the same concrete function/statement/defect site. A CSV-only performance-023 comment cannot match the vendor loop; a comment explicitly identifying both may match both. Severity MAE is over confirmed positive edges with known severities, not over comment TP.

The judge receives `sum((expected_in_file + ignored_in_file) * generated_in_file)` candidates, including retained mechanical gold; entries without candidates need no judge call. Missing, duplicate, out-of-range or non-boolean verdicts fail explicitly rather than silently becoming false. Results preserve every positive and negative semantic edge, its gold bucket/index, generated index and available reasoning in `judge_evidence`, alongside original gold arrays, protocol, prompt-template hash and source-patch hash. Generated text is already retained in the result. No raw prompt/environment/transcript is added to runtime uploads.

Each new result also contains `legacy_result`: the old one-to-one assignment over **the same new judge edges**, with the same mechanical-neutral exception. This is score-policy sensitivity, not reproduction of the historical prompt. The judge prompt changed, so old/new historical score differences cannot be attributed solely to assignment. Old serialized results default to `one-to-one` / `same-issue-v1`; they are not rewritten. Summaries/aggregates retain legacy and unscoped views and group by explicit scoring mode and judge protocol, rejecting mixed identities.

`CodeReviewResult.create` requires explicit expected and ignored match lists from the caller. It only computes metrics from those established matches; it never infers matches from comment locations or invokes the judge itself.

### Severity scope and paired score views

This experiment's primary score is **Medium-aligned** for every code-review runner. Gold below Medium is excluded from the recall denominator and added to the neutral matching bucket. Unknown-severity gold remains required. Generated comments are **never filtered by their self-reported severity**: a Low or unspecified output can still earn an in-scope match, and unrelated output still counts against precision. Any-match neutralizes repeated confirmed Low-only outputs; the labeled legacy view retains its ordinary neutral one-to-one capacity.

The judge evaluates the full expected/ignored candidate set **once**. The same edges produce four views: any-match and legacy assignment, each Medium-aligned and all-severity. All prioritize positive credit over neutral matches and exclude mechanical diagnostics. Scope alignment is not computed by subtracting historical false negatives or discarding generated comments before matching.

Results persist `minimum_severity`, `out_of_scope_comments`, `out_of_scope_matched_comment_count`, and the complete `unscoped_result`; run summaries and aggregates preserve `unscoped_summary` and `unscoped_aggregate`. Console/Actions reports show the floor, excluded/neutral counts and both score views; export metadata includes `scoring_scope` and `unscoped_*` metrics. Aggregation rejects mixed severity scopes or mechanical policies. The unscoped view uses **all severities of review findings in the corrected current dataset**, not a rewrite of historical scores or a requirement to report mechanical gold. Invalid output receives no neutral credit and an entirely invalid run cannot become perfect merely because all its gold is outside scope.

### Retained compiler/analyzer gold

`ReviewComment.kind` distinguishes `review_finding` (default), `compiler_diagnostic`, and `analyzer_diagnostic`. Classification alone retains records in `expected_comments` without changing their bodies, locations, severities or articles; separately adjudicated gold corrections are recorded with before/after evidence. That collection's legacy name no longer makes every record a required positive. `diagnostic_id` records the established rule, such as `AA0216`, independently of severity. Compiler syntax errors are not mislabeled as warnings; where no compiler was executed, the diagnostic ID remains unspecified rather than invented.

Mechanical gold never enters TP/FN in either score view. An output is neutral only after a same-file semantic judge match to such gold, **not** because the output labels itself a diagnostic. Every matching mechanical output is neutral, including repeated reports, unless it also earns positive credit. In legacy this is a neutral-only capacity exception; any-match allows all confirmed neutral-only outputs. Each generated output is counted at most once; mechanical provenance takes precedence over other neutral buckets for diagnostic subtotals.

Results preserve the typed `mechanical_comments`, `mechanical_matched_comment_count`, and `mechanical_diagnostics_neutral` policy identity; summaries and exported metrics retain their counts. The [full classification inventory](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/mechanical-gold-scope.json) now maps all **145 entries / 300 gold records: 56 analyzer diagnostics, 9 compiler diagnostics, and 235 retained review findings**. Of the review findings, 218 are Medium-or-higher and 17 are Low. Its original 233-record / 45-neutral snapshot remains intact; explicit current-record mappings and before/after decisions preserve reworded, reclassified and retired records rather than reusing historical indexes.

Classification relies on demonstrated standard-tool capability, not proof that the original app enabled or ran the analyzer. The bounded effective-v2 review applies AA0218 consistently to 11 ordinary page-field findings: ten Normal source fields and one FlowField cue, with no tooltip on either declaration and no evidenced structural exclusion. These are neutral, not new business findings. Cross-statement dataflow, dependency-sensitive SIFT, semantic classification and XML-doc gold are not neutralized merely because they overlap a rule name. No AL compiler/analyzer execution is claimed.

### Audited gold corrections

The [run 39616090167 audit dispositions](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/run-39616090167.json) preserve all 97 original missed-gold slots and their original decisions: **4 fixed, 17 reviewer follow-ups, 46 unresolved, 8 severity-aligned, and 22 mechanical-neutral**, with explicit subsequent wording reassessments. Initial repairs correct an unsafe mandatory `ModifyAll` replacement, a public-API claim about an internal `RecordRef` helper, silent BOM persistence instead of downstream validation rejection, and an `Err` label already used by `Error`. The later integration also retires upgrade-005's physical-table migration expectation: its actual `a29ca6a` base defines O365 Contact as Temporary and Pending under CLEAN29. No speculative replacement defect is invented.

The style-012 false-delivery-success repair is **not recovery of an original FP**: F001 was already credited against G05's commented-out-code claim. Both were Medium, not Low. The completed granularity review clarifies original G05 to describe the unperformed send and false success, retiring the later duplicate functional addition. One cause/fix therefore requires one match, not two; the historical assignment is unchanged.

The [322-comment integration ledger](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/run-39616090167-unmatched.json) preserves every original unmatched ID across 103 entries, candidate/comment hashes, both adjudication axes, evidence limitations and individual integration decisions. Effective-v2 dispositions are 80 missing-gold candidates, 5 matching/granularity, 7 duplicate, 21 mechanical, 50 severity-scope, 78 substantive false positives and 81 unresolved. The separate factual axis is 148 supported, 55 incorrect, 39 mixed and 80 unresolved; neither axis is a corrected precision score.

Of 41 concrete additions, 37 are accepted, one already exists and three are deferred. Six of 31 constrained proposals are accepted individually; 25 remain deferred. All eight XML/public-API policy proposals remain deferred. The seven mixed missing-gold cases are narrowed to supported HTTP-status/retry concerns, excluding false transport-error and unverified provider-idempotency claims. Whole-dataset checks add seven equivalent HTTP defects even where no historical candidate reported them. In total this integration adds **50 semantic findings and 19 neutral diagnostics**, reclassifies existing style-018 G01 as neutral and retires two records. Five of six gold/matching correction proposals are applied; consent-registration granularity remains explicitly deferred. All 145 source patches and base commits are unchanged by this integration.

Uncertain gold remains in place pending missing context; raw XML-doc findings filtered at the output threshold remain a severity-calibration question. Historical matching was one-to-one; the new any-match policy does not retrospectively change those records. The audit is not a corrected precision estimate: the historical 137 completed entries yielded 105 matches out of 202 gold and 427 generated comments, while eight excluded positive entries contained another 31 gold. Removing all 23 Low gold from the frozen assignments gives only a scope-sensitivity calculation of 95/179, not 105/189 and not a new official score.

The dataset-first alignment against candidate knowledge `45cbe369` is recorded in the inventory's `alignment_review`: **80 missing-gold rows = 43 accepted + 1 already covered + 36 deferred**, including all eight XML/API policy questions. All 22 original mechanical misses remain typed analyzer records (17 AA0216 and one each AA0248, AA0018, AA0013, AA0001, AA0137), not deleted answers. `current_gold_records` joins each original snapshot or candidate decision to the current entry/index and normalized gold hash; `proposal_decisions` records individual acceptance limits and deferral reasons.

The bounded nine-article check found two retained locking claims needing narrower wording: performance-007 G01 no longer asserts that update locks block every reader, and performance-015 G02 no longer calls `FindSet(false)` a read-only cursor or asserts a mandatory per-row network round-trip. Their read-only/update-intent recommendations remain conditional on transaction requirements; no measured contention or speedup is claimed. A duplicated AA0216 citation in style-016 G03 is also removed. These are three body-only corrections: record counts, kinds, severities, locations, annotations and all source fixtures are unchanged. Exact before/after values and first-party documentation are in `integration_changes`; no new knowledge-based positive, matching policy or evaluation-code change is introduced.

Reassessment preserves the original audit judgments while withdrawing 17 literal-message findings as confirmed reviewer omissions: the frozen BCQuality style leaf excludes mechanical compiler/standard-analyzer diagnostics. Teaching-tip sibling precedent and the external upgrade-registration/idempotency contract also remain unverified. The user separately authorized mechanical neutrality and retention of typed records, including the root-origin pure syntax finding. This global scoring decision is explicit, not inferred from a style-leaf ban.

For the **initial 45-neutral snapshot's fixed-historical-assignment sensitivity only**, mechanical and Low exclusions overlap on six gold (one matched, five missed). Their union removes 51 gold (21 matched, 30 missed), leaving **84 TP / 67 FN / 151 gold: 55.63% recall**. Existing accepted judge edges supply no additional originally-unmatched output eligible for those initial neutral buckets, leaving 322 unmatched-by-gold FP and **84/406 = 20.69% precision**. This preserved calculation predates effective-v2 and all later gold additions/removals/rewrites; it is not a projection of the current 300-record dataset, an actual corrected score, or model improvement. New/reworded gold has no frozen matching decisions.

Any baseline/candidate rerun must use the same corrected dataset, scorer, applicable model settings, CLI, and severity thresholds. Report measurement corrections separately from reviewer improvements and retain the historical scores. The earlier publication hold is superseded only for the approved fixture-repair experiment below: experiment-classified storage is permitted, but leaderboard publication remains prohibited.

### Incidental fixture cleanup after the frozen comparison

The subsequent fixture-only revision changes 34 approved incidental convention observations across 23 cases: tooltip text, source-file names, caption casing, temporary-variable names, translation metadata, redundant comments, formatting, and equivalent terminating-branch layout. Intended defects, negative controls, deliberate normative positives, and all 225 required semantic Medium-or-higher findings remain unchanged. Existing gold is only relocated to its corresponding source lines; kinds, severities and retained finding bodies are preserved.

Eight repaired AA0218 expectations are retired (three in `error-clean-01`, two each in `error-testfield-enabled-01` and `perf-clean-01`, and one in `style-tooltip-mismatch-01`), together with the last case's table-anchor alias for that same repaired gap. Its misleading **Close action** tooltip remains unchanged, as does the dedicated `style-018` missing/inherited-tooltip boundary. The dataset now contains 145 cases, 299 full expected records (242 review findings, 48 analyzer diagnostics and 9 compiler diagnostics), and two explicit ignored records.

`tests/fixtures/codereview-incidental-cleanup-baseline.jsonl` preserves the 23 original rows so tests can reconstruct the frozen `5bef88326e6467a0f4f5ad265a6fdbb2ce679bb795cacbf92d7b4aad17b5b348` dataset without rewriting historical audit ledgers or evaluation results. The revised dataset SHA256 is `2499ef2792e99b7c02b983da5cd0c3810158968767b16705ec35a2338e5a844f`; any later evaluation must identify it as a separate dataset revision, not a reviewer-only improvement.

The proposed comment-only cleanup of `testing-tolerance-clean-01` is deferred: its original patch declares 42 added lines but contains 43, so rebuilding that hunk would also restore a closing brace ignored by patch application. This revision leaves that case byte-for-byte unchanged rather than silently repairing unrelated fixture structure.

Real AL compiler 16.4.41.14633, from the official BC 27.0.38460.54596 artifacts, compiled all 55 fixture AL files before and after cleanup in 23 separate projects. Fourteen project pairs compile successfully; the other nine preserve the same source-anchored diagnostics, with no observed cleanup-induced compiler errors. Existing syntax/type errors, omitted dependencies and product-object conflicts limit those nine builds; matching errors are not proof of complete semantic coverage. Fixture-owned runtime 15.0 manifests remain byte-identical; other projects use identical BC27/runtime16 validation envelopes and official W1 symbols, without stubs or source repairs. Target-matched CodeCop confirms six retired AA0218 findings disappear; the remaining two are source-validated but analyzer execution is blocked by the original missing `Sample Dispatch List` page. No runtime behavior validation or new model evaluation is claimed.

### Subsequent bounded style-fixture cleanup

A separate local fixture revision aligns 14 source-file names with their unchanged AL object names, moves the existing `Demo Spend Request Status` enum unchanged into its own file, and removes only 43 explicitly selected comment lines and three trailing comments across 14 cases. All other AL bytes remain unchanged, including intentionally malformed statements, held comments, XML documentation, and the misleading Close-action tooltip. `style-015` remains untouched. Gold changes are restricted to mechanical file/line mappings: all 299 expected records, 225 required semantic Medium-or-higher findings, two ignored records, and 145 case IDs are preserved.

The inline patches in `dataset/codereview.jsonl` are the canonical fixture sources. `tests/fixtures/codereview-style-cleanup-baseline.jsonl` preserves the 14 prior rows and reconstructs the exact `2499ef2792e99b7c02b983da5cd0c3810158968767b16705ec35a2338e5a844f` dataset for historical regression tests; old audit ledgers and snapshots are not rewritten. The new dataset SHA256 is `4c925f0f45c77018681e71f84fd3750bf918f12d6c15192d07024e9c52655235`. This revision does not change the engine, knowledge, scorer, or original experiment results, and does not include a new evaluation.

All 14 complete fixtures were compiled before and after with the same official BC27 compiler and W1 symbols used above. Eight pairs compile successfully, including the split enum; six retain exactly the same diagnostics after mapping file names and comment-deletion line offsets. Those existing syntax, missing-dependency and product-object conflicts remain limitations, not successful builds. No source stubs or repairs were introduced.

### Structured diagnostic compatibility smoke

The diagnostic experiment pins BC-ALAgents to
`4517a6d602700fb0eb5a6f598942028436a7dcaf`, a direct child of the previous
`17f5761d95ee08d47dd1a68571e84b1c440883c5` engine. CLI 1.0.88, BCQuality
`cb65498d5ca1c3456174b4c91971c912bb4a2a80`, models, severity, fixture data,
gold and scoring remain unchanged. Only one standard four-case smoke is
authorized; no automatic retry or full run follows. This tests diagnostic
compatibility, not a same-engine precision A/B against historical runs.

The failure collector no longer reads stdout/stderr. It independently validates
the exact engine `_cli-failure-diagnostic.json` schema and reprojects fixed
constants, bounded integers and existing scalar metrics. The frozen 19-leaf
manifest supplies bounded, unique work-directory names; the file's ordinal must
match its directory. Unknown fields, duplicate keys, unsafe paths and oversized
inputs are rejected without printing their contents. Missing evidence is
explicitly unavailable, never evidence of success or an inferred cause.

To keep the existing single-file upload at most 4 KiB, the artifact retains only
the first exception-path diagnostic in plan order and explicitly counts other
available diagnostics omitted from the artifact. Each retained engine diagnostic
has at most eight observations. The upload allowlist remains exactly
`failure-diagnostic.json`, with one-day retention; no raw streams, session files,
OTel, prompts or arbitrary server strings are added. Runtime manifests/traces
retain their existing separate per-process completeness and stage evidence.
CLI observations may describe retried requests and do not establish the terminal
cause. Root failures are outside the new leaf diagnostic's coverage.

### Bounded incidental defect repairs

This experiment follows `EXPERIMENT.md`: a draft PR, a four-entry Actions smoke run, then one complete 145-entry run. It retains the `a5d5df63e5140f46d94ee0ef90b698b33967647c` experiment chain and compares against frozen run `40500385865`, including its nine partial reviews and recovered-attempt provenance. A historical observation is not a simultaneous paired control; changes outside the seven repaired entries also expose run-to-run variation.

The branch transplants only the existing experiment-upload routing from [PR #986](https://github.com/microsoft/BC-Bench/pull/986): `bceval --eval-run-type experiment`. Both the PR's CI mock summary and the review workflow explicitly select experiment classification and skip the leaderboard. This permits experiment storage, not a no-publication guarantee; `mock` alone is not proof of no external writes. It does not merge main, change production pins, or alter the judge or score calculation.

The first standard smoke, run `40710492659`, failed on all four unchanged selected fixtures before scoring: the first leaf exited with code 1 and the engine's subsequent usage-completeness assertion obscured its exit diagnostic. The approved diagnostic follow-up changes only post-failure retention. `tools/collect_pr_review_failure.py` scans at most 64 KiB from each first-leaf stream and exports fixed error-category signals, HTTP error status codes and validated scalar metrics; it never exports source text, unknown messages, prompts, credentials, environment dumps or raw OTel. The workflow uploads only the explicit `failure-diagnostic.json` file with one-day retention. Textual signals are not themselves proof of the underlying cause.

The next seven-case revision changes two unsupported `Verbosity::Information` members to `Normal`, uses `SalesLine.Validate("Line Discount %", DiscountPct)` before the existing `Modify(true)` in two discount helpers, enables `AutoIncrement` on two existing integer primary keys, and asserts the request helper's actual return value. The cancellation/SaveRecord positive, the non-editable FlowField's absent ShowMandatory negative, both formatting controls, and unqualified helper calls remain intact. Every non-patch entry field, including all expected and ignored comments, is unchanged; the other 138 dataset rows retain their exact bytes.

`tests/fixtures/codereview-fixture-repairs-baseline.jsonl` preserves the seven original rows and reconstructs the exact `4c925f0f45c77018681e71f84fd3750bf918f12d6c15192d07024e9c52655235` dataset before the historical style-cleanup reconstruction. The revised dataset SHA256 is `3c95551e17fc0dab821811f6bbe3d09853e55e9cb17f68951e021eaefbb2b1c6`; it is a separate fixture revision, not evidence of reviewer improvement.

Whole-fixture before/after compilation and CodeCop use the same official BC27 toolchain and W1 symbols in 28 invocations, without stubs or additional source changes. Six revised projects compile; `privacy-009` still fails because W1 lacks its existing `Federal ID No.` field and its unchanged five-argument `LogMessage` call has no matching overload, newly exposed after replacing the invalid verbosity. These limitations are not repaired by changing the fixture's locale or telemetry contract. Emitted symbols confirm both `AutoIncrement` properties, the existing style-006 AA0013 diagnostic remains, and the unused test-return variable warning disappears. Source-contract regressions and compilation do not execute two inserts, cancellation, Sales Line recalculation, or the assertion in an AL runtime. No app publication, model evaluation, knowledge, engine, or scorer change is included.

### Current experiment: no knowledge versus narrowed BCQuality

The completed no-knowledge comparison superseded the earlier original-knowledge/candidate pair described below. It used `pr-review-evaluation.yml` with `review-integration=none` versus `bcquality`, explicitly `test-run=false`, `modified-only=false`, `repeat=1`, root model `gpt-5.6-sol`. The enabled engine was `25817a39a67b9e883f1a8ea9624283ab2b41af9b`, pinning BCQuality `41b0b7a39f890d904fd00f3a5c61582573c9adf8` (version 1.9). Both runs used the full nonempty engine SHA for the publication guard; the plain arm did not execute the checked-out engine or prepare BCQuality.

The plain arm reuses `bcbench evaluate copilot --category code-review --isolated-review`. This opt-in mode, not the ordinary Copilot harness, creates a disposable home/configuration, uses an environment allowlist, disables hooks/IDE connection and custom instructions, disables every CLI-discovered skill, and requires an empty plugin inventory. CLI 1.0.88 discovery commands and flags were probed without model calls. Before/after inventories, fixed flags/configuration, prompt/source hashes, status and numerical usage are retained in `_plain-review-evidence.json`; no raw environment, prompt or transcript is uploaded. Inventories establish available configured sources, not omniscient proof of every file the model reads.

All ten fixture base revisions contain `.github/agents`, which this CLI cannot globally disable. With explicit user approval, only the GitHub-hosted job's disposable `GITHUB_WORKSPACE/testbed` clone may temporarily move that exact, clean tracked directory outside the checkout. Its tracked files are marked skip-worktree for the duration so **ordinary `git diff HEAD` tool calls remain byte-identical**, not just a filtered prompt display. The directory is restored and flags cleared in `finally`; per-file configuration/source hashes and before/isolated/after diff hashes are retained. Dirty configuration, unexpected index flags, live/local checkouts, other conflicting configuration, restoration failures or source/diff changes fail closed. A recovery conflict preserves the original quarantined bytes rather than deleting either copy. No AL/JSON fixture or gold is changed, and no general exclusion/deletion mechanism is added.

Both arms use native CLI 1.0.88 with updates disabled, the same source fixtures and judge/scorer. Plain review explicitly requests Medium-or-higher output and disables skill/task tools; enabled review retains both Medium floors, serial `gpt-5.6-luna` leaves and a `gpt-5.6-sol` root. **Single generic invocation versus 19 leaves plus root is an intentional whole-integration ablation**, not an isolated test of five knowledge edits. The scorer never drops generated comments by their self-reported severity.

The plain arm unconditionally enables mock summarization and disables requeue; the enabled arm requires nonempty `engine-sha` to keep storage and leaderboard disabled. Runtime artifacts stay separate from evaluation JSONL. Summary retention in mock mode is one day, so download promptly. Report all-selected metrics, complete/partial/failed status and symmetric complete-case sensitivity separately, including per-entry improvements and regressions tied to exact comments. One pair on this audit-derived (not held-out) dataset establishes neither statistical significance nor generalization. Do not start either run until exact-head checks and launch approval are complete.

### Previous pair and preserved observations

 `9607dea1c84fcf660983a5e3791dece1fb2f1623` plus the optional child-environment forwarding fix `10086e6d19f37d4e9d419480cc38aa1615ef8954`: baseline `38180ca61e4b7ad34bec1889f3c16d7d1c113a82` declares BCQuality `a4593a1b1585a0fa663efbf39ff02c60f846d851`; candidate `4b5c5ce6ccf759ffde24c4558c113601c873c75c` declares `45cbe369527bbe6d4cad0b2a877bd1d61a617cdb`. Their full engine diff changes only that knowledge ref, although baseline is not candidate's direct parent. Knowledge remains version 1.9, Microsoft-only; the candidate changes nine existing articles / 28 files, not merely the initial two articles. Both arms use root `gpt-5.6-sol`, serial leaves `gpt-5.6-luna`, judge `gpt-5.3-codex`, CLI **1.0.88**, and both severity floors **Medium**. The revised dataset SHA256 is `42178a85e9e8ce023f32ef030a95f2c2829f76268d47cac47c8beafd577a8a30`.

The job installs exact CLI 1.0.88 in an isolated directory and puts its native executable directory first on PATH; no launcher or floating `npx` resolution is used. The installation check uses `--no-auto-update --version`. Evaluation explicitly sets `COPILOT_AUTO_UPDATE=false`, which both new engine revisions forward to their cleared child environments. **CI alone does not freeze the CLI**: with a newer cached executable present, the real environment helper selected 1.0.102-1 when the setting was absent, versus 1.0.88 in three consecutive version-only probes with `false`. Startup and observed-version/model checks remain fail-closed. The actual installer also passed a native version probe from a path containing spaces. The engine's new environment tests pass; three pre-existing schema-message assertions fail both before and after its environment fix.

Both immutable BC-Bench arm commits belong to this draft experiment PR. A future full run must set `engine-sha` **equal to the checked-in pin** to retain the existing no-publication guard; it is not an alternative BCQuality override. Use the full 145-entry corpus, not `modified-only`, with `repeat=1`: **290 entry jobs**, planning 290 root plus 5,510 serial leaf CLI processes (19 declared leaves per entry), plus at most **228** entry-level judge invocations (114 entries with expected/ignored records per arm). CLI processes are not model API calls; tool turns, retries and repairs can increase actual requests. No automatic repeat is authorized.

**This earlier pair was paused for dataset review and is superseded by the current experiment above.** The earlier Bench pair `93069371a78fbe9612fa02640b2543b6f56ddd42` / `fbac2753c0d139268d973c6ad3439449664bfd40` contains dataset `f30803905a7a1235688d151384490ce1f998214d614dea8ad117ed49bbcb39a4`, not the revised data above. Baseline [run 39773340119](https://github.com/microsoft/BC-Bench/actions/runs/39773340119) preserves 145 result/runtime pairs, with 130 completed and 15 partial engine reviews; those outputs are not rewritten or treated as results for the new gold. Candidate was not dispatched. The baseline BCQuality revision also differs from historical `b74967bc`; historical-to-candidate changes cannot isolate the effect of the candidate knowledge repairs. Workflow dispatch must resolve a branch/tag to the intended immutable Bench commit; the `git-ref` input is a tracking label, not a checkout selector.

Each PR-review entry also uploads a separate `runtime-evidence-<run-id>-<entry-id>` artifact. The engine writes `_run-manifest.json` and `_run-metrics.json` directly into `evaluation_results/<GITHUB_RUN_ID>`; the workflow explicitly preserves the CLI's existing `GITHUB_RUN_ID` option override rather than using its local default directory. This directory is reset before the entry starts, not removed when the agent returns. An always-run collector reads these files after evaluation and exports runtime/commit identity, model and severity configuration, leaf plan, process status/timing/exit codes/observed models, and aggregate numerical usage. It omits raw failure text (retaining presence flags), report paths, source snapshots, prompts, transcripts and environment data. The accompanying `evidence-status.json` records entry/run/commit identity, original and projected file hashes, and explicit missing/invalid states. Upload names exactly these files and the bounded trace below, not a directory wildcard. Result summarization downloads only `evaluation-results-*` artifacts for BC PR Review, preventing runtime JSON collisions or accidental inclusion in scoring. Sources and scoring are unchanged.

A successful evaluation step fails its evidence gate if either required JSON is missing/invalid or the manifest is still running/failed, including a handled agent timeout that otherwise returns a successful command exit. A partial manifest remains explicitly partial, not a claim that every leaf completed. On an already failed/cancelled evaluation, available evidence is retained and omissions are warnings without replacing the original failure; a skipped evaluation never reuses stale evidence. Both collection and upload run on failure, subject to the runner remaining available. These bounded JSON artifacts contain no result JSONL files and do not enter scoring. Full experiment artifacts are retained for 30 days; execution still requires coordinator approval of the newly frozen pair and its exact-head CI.

### Bounded finding provenance

Instrumented engines declare `trace_schema_version: 1` in the manifest and emit `_review-trace.json`, using the engine's `review-trace.schema.json` contract. The collector retains only candidate identity (`l<leaf ordinal>-f<zero-based original finding index>`), original report hash, leaf ID, admission state, provided article references, source location/severity, two fixed normalization codes, and bounded candidate prose. Bodies are limited to 1,024 characters and retain the engine's `retained`/`truncated`/`redacted`/`omitted` status. Engine redaction is defensive, not a guarantee against arbitrary secrets. Suggested code, raw reports and envelopes are not collected.

The trace also retains explicit root dispositions (`kept`, `merged`, `downgraded`, `removed`, `unknown`) and fixed diagnostic stage/code/status/exit-code fields. Root reasons are enum-only, never free text. Missing or invalid root declarations remain unknown; counts or textual similarity must not manufacture lineage. `final_index` addresses **`_review-report.json#/findings`, zero-based, before engine filtering**; it is not the index in normalized engine output or BC-Bench's `F001` numbering. No implicit join to scored comments is made. Article references identify supplied attribution, not proof the article was read or caused the finding.

The collector enforces a 4 MiB trace read limit, 1,000 candidates/final findings/dispositions, 128 diagnostics, eight references/target indices, bounded repository-relative paths, enum/type checks, unique IDs and valid references. Unknown fields are omitted; invalid allowlisted values reject the projected trace without echoing payloads. Truncation remains explicit. Missing trace is `not_available_legacy` only when a valid manifest has no trace declaration; instrumented-engine missing/invalid traces fail the evidence gate after successful evaluation. Earlier failures retain available evidence without replacing the original failure. The raw `_root-dispositions.json` sidecar is never uploaded.

### Next knowledge-only comparison (not yet authorized)

Historical runs [39808393341](https://github.com/microsoft/BC-Bench/actions/runs/39808393341) and [39809706078](https://github.com/microsoft/BC-Bench/actions/runs/39809706078), their `d581548d` implementation, dataset and scores remain immutable. The next proposed pair uses BCQuality in **both** arms: baseline `41b0b7a39f890d904fd00f3a5c61582573c9adf8` versus a reviewed narrow candidate. Both must share instrumented engine code/root prompting, configuration, 19 serial Luna leaves plus Sol root, CLI 1.0.88, Medium thresholds, frozen dataset `42178a85e9e8ce023f32ef030a95f2c2829f76268d47cac47c8beafd577a8a30`, any-match scorer and `specific-site-v2` judge. Only the declared immutable knowledge pin differs. Instrumentation itself may affect model output, so historical runs are not an instrumented baseline.

Predeclare normative-comment volume, source-adjudicated noise with explicit scope, functional unique-gold retention, overall P/R/F1 and execution/trace completeness. Reuse the lost-gold cases as diagnostic checks, never as a new primary selection or gold rewrite. Report all available outputs and the symmetric complete-case intersection separately. The current audit-derived synthetic benchmark is not held out; no independently human-adjudicated, unexposed real-PR holdout is currently confirmed. Final pins, exact-head CI and parent review must precede any dispatch. Use nonempty approved `engine-sha`, mock/no publication and `repeat=1`; no retries, extra no-knowledge runs or merges are authorized.

## Category and runners

`code-review` is the evaluation contract: it owns the dataset, structured `review.json` output, scorer, result schema, and leaderboard schema. A runner is the system under test. The same entries can be evaluated through the generic GitHub Copilot CLI and Claude Code runners, allowing direct cross-system comparisons under one scorer.

BC PR Review is a separate agent harness fixed to the `code-review` category. It runs the production BC-ALAgents review engine with BCQuality, while generic Copilot and Claude runners continue to use their own prompts and configuration:

```text
bcbench evaluate copilot <entry> --category code-review
bcbench evaluate claude <entry> --category code-review
bcbench evaluate pr-review <entry>
```

BC-ALAgents is the PR Review harness boundary. Its repo and default commit are pinned with the other harnesses in `.github/actions/install-agent-harnesses`, and that engine commit owns the BCQuality version through its own configuration. Changing the *default* pin still requires a new BC-Bench version and must record the BC-ALAgents commit SHA in the release notes.

For a durable experiment, push the pipeline and/or BCQuality changes through a BC-ALAgents branch, update the action pin to that immutable commit, then run BC-Bench from a branch with a draft PR describing the experiment (see [EXPERIMENT.md](https://github.com/microsoft/BC-Bench/blob/main/EXPERIMENT.md)). This keeps the reproducible dependency chain BC-Bench -> BC-ALAgents -> BCQuality, and records why the revision was evaluated.

The `pr-review` workflow also accepts an `engine-sha` input — a full 40-character BC-ALAgents commit SHA — as a **convenience** for a quick look at a revision without branching or re-pinning. It does not replace the process above: nothing records the intent behind the run, so an override is scored but never published to Braintrust/Kusto or the leaderboard. Blank keeps the default pin, requeued repeats retain the override, and the SHA that ran is recorded as `agent_version` on every result — read it from the job summary and run artifacts.

Either way, hold everything else fixed: the benchmark version, the model, the Copilot CLI version the engine uses internally, and the configured minimum severity. Locally, `bcbench evaluate pr-review --engine-path <checkout>` requires a clean engine checkout and uses the configured severity; use `bcbench run pr-review` for dirty-checkout smoke tests or `--min-severity` overrides.

BC PR Review records wall-clock duration, prompt/completion/total tokens, and exact AI credits. Usage values come from the engine's strictly validated schema-v1 `_run-metrics.json`, never from console transcripts. API-call details, knowledge-filter counts, token subcategories, completeness diagnostics, and producer metadata remain in that raw artifact rather than being promoted into BC-Bench result and leaderboard schemas.

Unavailable AI credits remain `null` in bceval exports; observed zero remains zero. The pinned bc-eval 0.6.1 consumer requires numeric prompt/completion tokens, so its existing zero fallbacks for missing tokens remain unchanged. Use the original per-entry result metrics, not bceval token fields, to distinguish unknown usage from measured zero.

## Baseline Leaderboard

{% if site.data.code-review.aggregate and site.data.code-review.aggregate.size > 0 %}
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>Micro F1 (95% CI)</th>
      <th>Precision</th>
      <th>Recall</th>
      <th>Valid Output</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.code-review.aggregate | sort: "f1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null or agg.experiment.is_experiment == false %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.f1 | times: 100.0 | round: 1 }}%{% if agg.f1_ci_low %} ({{ agg.f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.f1_ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{{ agg.precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.recall | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.valid_review_output_rate != null %}{{ agg.valid_review_output_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>
{% else %}
<p><em>No results available yet. Check back soon!</em></p>
{% endif %}

## Performance Leaderboard

{% if site.data.code-review.aggregate and site.data.code-review.aggregate.size > 0 %}
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>Avg Time</th>
      <th>Avg Prompt Tokens</th>
      <th>Avg Completion Tokens</th>
      <th>Avg Total Tokens</th>
      <th>Avg AI Credits</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign performance_results = site.data.code-review.aggregate | sort: "average_duration" %}
    {% for agg in performance_results %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td>{% if agg.average_prompt_tokens != null %}{{ agg.average_prompt_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_completion_tokens != null %}{{ agg.average_completion_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_total_tokens != null %}{{ agg.average_total_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_ai_credits != null %}{{ agg.average_ai_credits | round: 4 }}{% else %}—{% endif %}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p><em>No performance results available yet. Check back soon!</em></p>
{% endif %}

## Experiment Leaderboard

Compares review-knowledge configurations for the same model (see the Baseline Leaderboard above for the plain agent):

- **Inline knowledge (pre-#8700)** — the review checklists BCApps shipped inline before adopting BCQuality, injected as custom instructions.

{% assign experiment_rows = site.data.code-review.aggregate | where_exp: "agg", "agg.experiment != null" %}
{% assign experiment_rows = experiment_rows | where_exp: "agg", "agg.experiment.is_experiment != false" %}
{% if experiment_rows and experiment_rows.size > 0 %}
<table>
  <thead>
    <tr>
      <th>Variant</th>
      <th>Agent</th>
      <th>Model</th>
      <th>Micro F1 (95% CI)</th>
      <th>Macro F1 (95% CI)</th>
      <th>Precision</th>
      <th>Recall</th>
      <th>Valid Output</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign experiment_results = experiment_rows | sort: "f1" | reverse %}
    {% for agg in experiment_results %}
    <tr>
      <td>
        {%- if agg.experiment.custom_instructions -%}Inline knowledge (pre-#8700){%- else -%}Other{%- endif -%}
      </td>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.f1 | times: 100.0 | round: 1 }}%{% if agg.f1_ci_low %} ({{ agg.f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.f1_ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{{ agg.macro_f1 | times: 100.0 | round: 1 }}%{% if agg.macro_f1_ci_low %} ({{ agg.macro_f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.macro_f1_ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{{ agg.precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.recall | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.valid_review_output_rate != null %}{{ agg.valid_review_output_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p><em>No experiment results available yet. Check back soon!</em></p>
{% endif %}

## How metrics are computed

- **Precision** — of the scorable comments the agent generated (generated minus ignored), the fraction that matched an expected finding. Penalizes noisy reviews.
- **Recall** — of the expected findings, the fraction the agent caught. Penalizes missed issues.
- **F1** — harmonic mean of precision and recall; balances both equally (the β=1 case of Fβ).
- **Fβ (β=0.5)** — precision-leaning F-score; use when false positives are costly (noisy reviews waste reviewer time).
- **Fβ (β=2)** — recall-leaning F-score; weights catching issues more than avoiding noise.
- **Severity MAE** — mean absolute error between the agent's and the expected severity levels, over matched comments only. Lower is better; `0` means every matched comment got the severity exactly right.
- **Ignored** — generated comments matched to gold that the recorded policy treats as neutral: ordinary `ignored_comments`, below-scope severity, or mechanical diagnostics. These are excluded from precision (they are neither correct nor incorrect); the count is surfaced for transparency only.
- **Valid output rate** — fraction of tasks whose output parsed into a structured review. Failures score zero on every other metric. (Reported per run.)
- **Micro vs. Macro** — *Micro* sums matched, scorable generated (generated minus ignored), and expected across all tasks (tasks with many comments dominate); *Macro* averages per-task scores (every task counts equally).
- **95% CI** — confidence interval bootstrapped over the per-task F1 scores, so the leaderboard reports sampling uncertainty even for a single run. The micro `F1` CI resamples runs; the `Macro F1` CI resamples tasks.

[← Back to Home](index.md)
