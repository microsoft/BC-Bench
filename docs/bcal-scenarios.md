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

BCal receives `--scenario`, `--result`, `--exportfolder`, and `--include-evidence` arguments. BC-Bench captures the complete `evaluation-run.json` through the shared harness transcript channel, reads structured trace events first, and can fall back to the archived `chat.json`. A nonzero exit with a step-associated failure and successful export/archive is preserved as a measured agent outcome; missing/invalid results, session-level failures, and export/archive failures are surfaced as harness failures.

Evaluation combines:

1. Deterministic scenario completion and trace assertions.
2. Independent standalone AL compilation when the `al` compiler is installed. If only symbols are available, the result explicitly records `not_attempted`; it is never reported as a successful build.
3. Optional runtime verification (currently `null` in the pilot entries).
4. LMChecklist scoring over the task, confirmed scripted decisions, deterministic summaries, exported workspace diff, and complete textual workspace.

The pilot entries span an inventory-risk feature, an integration-choice interaction, and an explicit plan-first lifecycle.

## Isolated reasoning compatibility diagnostic

The separately authorized `reasoning-compatibility` workflow phase is not a gold evaluation or a default-policy change. It pins BCAL `30.0.46.49019-beta` and probes `gpt-56-reasoning-sol`, `gpt-56-ceres`, and `gpt-55-chat` with explicit `none`, explicit `medium`, and omitted effort. All eighteen cells use synthetic prompts and one harmless echo tool.

The legacy lane invokes the production Python bridge with a diagnostic loopback client; the native lane uses the packaged SDK generator and unchanged production request handler with synthetic session configuration. Neither claims full task execution, production prompt/catalog parity, judge scoring, or reasoning quality. Native requested omission may generate wire `medium`; receipts distinguish requested, applied, and actual wire effort.

Admission verifies the exact archive and installed runtime files, runs native offline captures, and enforces a shared pre-send ceiling of 24 provider HTTP attempts plus one attempt per cell. HTTP errors and transport failures consume the budget; redirects, automatic replacements/reruns, and provider retries are not admitted. The one separately authorized setup-failure replacement is hard-pinned to the previous run's source and skipped certificate/inference steps, proving its zero provider attempts. Only sanitized status, shape, effort, identity, and numeric usage receipts are retained. Historical governed-study allowlists and production equality guards remain unchanged.

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

## Paired full-gold follow-up

The separately approved full-gold follow-up uses
`experiments\bcal-full-gold\study.json` and the existing evaluation workflow's
`full-gold-preflight` / `full-gold` phases. It selects all 110 ordinary gold cases
once per runtime (220 attempts), no challenge or authority cases. The exact
main alias is `gpt-56-reasoning-sol`, now with explicitly approved `none` on both runtimes;
the judge remains `gpt-56-ceres`. Each pair runs sequentially and the workflow
admits at most 32 pair workers total. A same-SHA gate verifies package/symbols
without inference, then performs at most five bounded protocol/routing requests
(two main Chat, two main Responses, one judge Chat), separately accounted from
semantic attempts, stopping at the first failure. Chat admission preserves the
production legacy envelope: tools present, `max_completion_tokens=16384`,
no `tool_choice`, with approved `reasoning_effort=none` applied by the governed
command bridge. The actual legacy CLI request has no effort field, so its
requested identity remains unset rather than falsely reporting a runtime option.
SDK runs explicitly pass `--sdk-reasoning-effort none`; both protocols are checked
at the outbound transport boundary, with rejected requests blocking completion.
Responses admission uses synthetic input/tools, `parallel_tool_calls=false`,
`reasoning.effort=none` and bounded max1024, not a native output-cap parity claim.
Actual packaged SDK serialization/guard proof must be bound before same-SHA
admission; requested effort metadata alone is insufficient.
The full-gold selector pins the governed `30.0.46.40357-beta` package from build
3054921, source `5f6e2ffbdb2ea8360e9f0f52074413114d7c885a`. Its hash-bound
`runtime-effort-proof.json` records actual packaged native serialization through
the production handler and mismatch rejection before HTTP. Offline capture is
not provider/domain success; the helper catalog does not replace the retained
context-specific study catalog. Package-build setup accounting is separate from
Bench Actions usage and must not be double-counted.
All earlier default-effort failures and direct probes remain charged separately,
not reinterpreted as successful admission. No automatic retry loop is permitted.
Prior studies and their limits/seals remain
historical; the user approved extending the previous aggregate limit for this fixed workload,
not a new monetary or numeric ceiling. Actual all-job usage must be reported.
The existing smoke selection and ordinary/scheduled defaults are unchanged.

Governed legacy attempts also retain content-free `legacyDiagnostics` before
cleanup: upstream header status versus body/transport failure, fixed bridge
input/client/serialization/output stages, response shape, and UTC observation
times. Existing request counts, effort audits and sticky-route checks remain
unchanged. A successful header or emitted command response does not prove
successful product-side parsing. Missing diagnostic files remain unavailable;
unrecognized classifications remain null. Interrupted trace event types and their
allowlisted operation/status/reason enums survive projection alongside their
existing hashes. Raw responses, exception strings and private logs are not
published. Product-side command launch/exit and parsing classifications require
an additive runtime emission contract; Bench cannot reconstruct those from the
generic exit-1 wrapper or retroactively recover the sealed historical exceptions.
The producer's optional `modelFailure` stays on the correlated `model_interrupted`
event. Bench preserves its actual snake-case stage/category values and optional
signed 32-bit exit code, plus hashed call/step/composition identity and numeric
prompt-use sequence. It does not coerce guessed enum casing or copy the exception
into a duplicate top-level schema. An observed `unknown` enum is distinct from
missing or unrecognized fields.

The governed command bridge emits and flushes explicit UTF-8 response bytes,
independent of Python's child stdout encoding, for both delivery and
completion-assessment requests. Response content and reasoning policy are
unchanged. Output encoding failures retain the allowlisted `unicode_encode`
category at the output stage, rather than being mislabeled `body_decode`;
write/flush failures retain `command_io`. An `emitted` receipt follows a
successful flush, not merely a buffered write. This fix does not recover
historical exceptions or authorize another admission or model-backed run.

The user-authorized diagnostics repeat has separate
`full-gold-repeat-preflight` and `full-gold-repeat` phases. Its
`bcal-full-gold-repeat` profile inherits the hash-bound original manifest without
modifying historical selectors, policy, or results. The original and repeat each
retain their own once-only dispatch guard. The baseline pin identifies the exact
historical Git LF bytes; only CRLF checkout line endings are normalized before
verification, not JSON content, whitespace or selection changes.
The repeat pins diagnostic package
`30.0.46.42492-beta`, build `3057056`, source
`8178001108d3147df9e4b367f87536d6f3665479`, with hash-bound native effort and
actual packaged command-client/collector events verified through Bench projection.
The six command/response stage families are present; `command_io` coverage proves
pre-cancellation, not arbitrary non-cancellation stream failures. Missing package
or proof bindings stop setup before installation, never implicitly install latest.
These offline proofs are required before the separate same-SHA hosted admission
and any of the same 110-by-2 attempts; they do not prove provider/domain success.
The repeat preserves explicit none, Ceres, scoring, sequential pair order and
maximum 32 pair workers; its measurements are disjoint from the original run.

The separately authorized `full-gold-legacy-preflight` / `full-gold-legacy`
phases use `bcal-full-gold-legacy-utf8`: the same 110 gold entries, legacy once
per entry, Sol `none`, Ceres and up to 32 workers. No SDK runtime slot or
Responses probe is selected. Admission performs two real command-bridge Chat
requests with sticky replay and one judge request, after exact package/symbol,
fixed-source UTF-8 and safe diagnostic-producer/consumer proofs pass. Its
once-only dispatch guard and measured accounting are independent of both
completed paired runs. Existing `sdk-policy-*` artifact names are retained
for the shared evidence collector; each case receipt admits only legacy.

The separately approved `full-gold-judge-preflight` / `full-gold-judge` phases use
`bcal-full-gold-judge-diagnostics`: the same frozen 110 gold cases once per
legacy/SDK runtime, Sol explicit `none`, unchanged Ceres checklist scorer,
diagnostic package42492 and at most32workers. Same-source admission requires
two actual legacy bridge calls, two Responses routing calls and one actual
pinned checklist judge call. No cell retries, replacements or rejudging.

Judge command exit/timeout, client HTTP/transport/timeout and response/checklist
failures retain allowlisted `judgeDiagnostics` on each attempt and in the
terminal report. Numeric HTTPstatus, exitcode, bounded numeric Retry-After and
request-ID SHA256 are retained when available; raw requestIDs, error messages,
bodies, prompts, source and credentials are excluded. Missing diagnostic evidence
is explicitly unavailable. Malformed, missing or duplicate checklist answers are
unscored judge failures, not zero quality. Valid boolean negative answers still
use the unchanged scorer. Failed judging surfaces as job/report failure after
both already-authorized runtime slots when cleanup is verified, without retries;
unsafe cleanup or other invalid evidence still stops the pair.

The separately approved `full-gold-review-preflight`, `full-gold-review-1` and
`full-gold-review-2` phases prepare two repetitions of the same 110-by-2 gold
selection with a new package containing stronger completion review. They use
one immutable `bcal-full-gold-strengthened-review` profile and one successful
same-source admission, normal Ceres scoring only, Sol explicit `none` and the
same 350 symbols. No diagnostic-subcriteria calls are selected. The two named
repetitions admit exactly 440 semantic executions in total, not replacements.
The second repetition reverses runtime order within each case; repeat identity
is retained in every attempt and summary.

Both phases share workflow concurrency and at most32semantic workers; the
second is admitted only after the first finishes successfully at the same
source. Failed admission or repetition is retained, never automatically
retried or replaced. Setup requires the actual new package's source-bound
review-prompt proof, preserved native/catalog and explicit-none fidelity,
packaged command-failure evidence, UTF-8 bridge proof and normal-judge
diagnostics. Historical package42492 cannot satisfy this new review gate.
Package publication/proofs are owned separately from Bench admission and job
accounting. Installing this workflow support does not admit an unpublished
package or missing proof.

Final reports separate each repetition and mutually judged case pairs.
Repeated observations of the same110cases are dependent: pooled440execution
counts are not440independent tasks. Missing scores remain unknown. Neither a
single successful repetition nor pooled descriptive averages establish
superiority or noninferiority.

### Diagnostic subcriteria, separate from official judging

`scripts\bcal_judge_subcriteria.py` is an explicitly invoked diagnostic evaluator.
It never runs automatically in an evaluation, admission, or hosted workflow.
It requires a previously successful official `judge-output.json` and the matching
private `judge-input.json`; their bytes and SHA256 bindings remain unchanged.
The canonical parent checklist, pinned scorer, official judge request, scores,
and historical artifacts are not edited. A diagnostic invocation is **one
additional Ceres request**, requiring separate inference authorization and route
accounting; adding subquestions to the official request would otherwise change
that evaluation's prompt. No diagnostic inference is implied by installing this
support.

`experiments\bcal-judge-subcriteria\criteria.json` provides explicitly authored
decompositions for the six legacy shortfall cases and two SDK-lower contrasts.
Use `--instance-id` to select a case; exact input-text and parent-assertion hashes
must match. It contains 29 diagnostic subcriteria under nine canonical parents.
These are analysis aids, not a new official workload or a claim that the
decomposition independently proves complete semantic equivalence to its parent.
For another task, `--subcriteria` may instead supply a single specification with
`schemaVersion: 1` and `parents`; each parent has `assertionPosition1`,
`assertionSha256`, and at least two unique `{id, text}` subcriteria.

An authorized caller can invoke:

```powershell
python scripts\bcal_judge_subcriteria.py `
  --input <private-judge-input.json> `
  --official-output <official-judge-output.json> `
  --subcriteria experiments\bcal-judge-subcriteria\criteria.json `
  --instance-id nl2al__expanded-sales-eligible-variant-picker-1 `
  --output <new-diagnostic-only.json>
```

The result contains parent-verdict provenance and separate `pass`/`fail`
subverdicts, never a replacement `quality`, `testPassed`, or parent verdict.
Subcriteria disagreements do not alter the official score. Missing, duplicate,
nonboolean or malformed judge results retain `status: failed`, all subverdicts
`unavailable`, and allowlisted judge diagnostics; the command fails explicitly.
HTTP/transport/timeout failures reuse existing no-retry judge handling. Private
temporary judge input/output and raw rationale are removed after projection.
Malformed input specifications fail before any request.

Optional `--source-references` plus `--source-root` accept private caller-supplied
evidence shaped as `{"schemaVersion":1,"criteria":[{"id":"criterion-id",
"references":[{"path":"relative.al","sourceSha256":"<SHA256>",
"startLine":1,"endLine":2}]}]}`. Only actual files inside the supplied source root
with matching byte hashes and valid UTF-8 line ranges qualify; path escapes,
stale hashes, duplicate references and unknown fields fail explicitly. Retained
references contain only source hashes and line numbers, never paths, AL snippets
or rationale. Verification establishes **content and range only**, not the
correctness or relevance of a model/reviewer citation. References are checked
again before publication.

The current product review changes export no structured requirement-to-source
registry. Consequently, references are explicitly `available: false` unless an
owning caller independently supplies actual exported source and references.
Prompt/composition hashes and completion events are not fabricated source
citations or semantic proof. The caller must associate the supplied official
score file with its private input and retain their recorded hashes; this utility
does not reconstruct a missing original judge response or generated source.

The separately authorized `full-gold-none-probe` phase only checks explicit
`none` compatibility: one tool-bearing Sol Chat request, then one direct
Responses request, stopping on the first failure without retries or a judge.
Chat sends `reasoning_effort="none"` with production max16384; Responses sends
`reasoning.effort="none"` with `parallel_tool_calls=false`, synthetic input/tools,
and bounded max1024. Neither forces tool choice. The transport verifies the
outgoing effort and retains safe counters/diagnostics in a distinct artifact.
This is not gold admission, a default-policy switch, SDK execution/fidelity
proof, semantic validation, or sticky replay proof. Those closed probes did not
change the policy; the subsequent explicit user approval authorizes `none` for
gold only after actual SDK wire-effort verification and all admission gates.

## Bounded SDK/legacy compatibility smoke

The separate selector `experiments\bcal-sdk-policy\study.json` pins package
`30.0.46.34884-beta` (source `7fafd2d6afdabaf4c8b06a5d8b8712a6c27ee37d`),
350 exact symbols, the same four ordinary tasks from the corrected hosted study,
and the four repaired authority cases. Each runs once per runtime: **16 attempts
total**, not 16 per variant. This compares legacy+bcal with SDK+copilot policies,
not pure orchestration parity. It does not dispatch the historical authority
selector, calibration repetitions, full validation, or any replacement attempts.

The existing **Evaluation with bcal** Actions workflow isolates `validation-phase`
`preflight` and `smoke` from its ordinary/scheduled evaluation paths. Smoke
admission requires the successful same-SHA, same-manifest zero-model preflight
run ID. Preflight materializes all four production authority fixtures and verifies
their seed contracts and symbol bytes without calling a model. Eight pair jobs
run at most four workers, with the two runtimes sequential and counterbalanced.
The eight-hour aggregate ceiling includes preflight, setup, controllers, judges,
failures, cleanup, and reservations; historical charges and the unresolved local
pilot hold remain charged to the original envelope. Reruns and semantic retries
are not admitted.

Ordinary checklist quality and deterministic authority outcomes are reported
separately. Native tools retain namespace distinctions; authority ordering uses
complete canonical evidence and `scenarioStepId`, and a compile must follow the
last mutation in the event sequence. Missing evidence never proves compliance.
Native no-change/read-only turns do not acquire a blanket fresh-compile
requirement; runtime domain-completion invariants still apply.

`plan_action` remains the BCAL durable-plan contract, not SDK Plan-to-Autopilot
approval. No scenario approval translation or authority waiver is performed.
Packaged no-model RPC admission confirmed the contextual custom `ask_user`
callback, scripted acceptance/decline/cancel, and forbidden namespaces. The three
interactive cases pin their actual 32/31-tool catalog; retained intent has no
interaction channel and pins the 31/30-tool catalog. Diagnostic prompt hashes
are provenance, not substitutes for actual per-attempt identities. Availability
selectors such as `custom:ask_user` are distinct from the unqualified RPC lookup
name. These checks and the hosted preflight do not establish model authority
compliance or authorize waived interaction assertions.

Only sanitized scores, booleans, counts, known identifiers, hashes, trace
completeness, and exception classifications may be uploaded to this public
repository. Raw AL, prompts, transcripts, error text, package bytes, certificates,
and routing tickets remain runner-ephemeral. Detailed failures cannot be recovered
or rejudged from publication alone after teardown.

## Opt-in reasoning-enabled coding

`scripts\bcal_reasoning_coding.py coding` is a separate opt-in entry point for
actual packaged `bcal.exe` coding, not the synthetic compatibility probe. It does
not generalize the closed governed-study allowlists, change defaults, or admit a
gold run. It pins package `30.0.46.49019-beta`, source
`52f3f7f5dd2d26c83f2778d28ace9d47364b481b`, and verifies the retained archive
hash and all 224 runtime payload files before execution.

Supply a JSON configuration with `policies` (one entry per selected model),
`max_provider_attempts` (shared across all entries), `timeout_seconds` (per coding
process), and `page` (local symbol context). Each policy requires an exact `model`
(`gpt-56-reasoning-sol`, `gpt-56-ceres`, or `gpt-55-chat`),
`reasoning_effort` (`none`, `medium`, or `unset`), and `auxiliary: "forbid"`.
Unknown fields, aliases, null effort, and unadmitted effort values fail locally.
There is no inferred best-model setting or automatic fallback.

The runner uses SDK-native/copilot planning, the production BCAL prompt and
tools, a supplied local symbol directory, and a single-user-step scenario. It
does not inject a synthetic SDK configuration. `unset` genuinely omits the SDK
CLI option and clears inherited overrides; this pinned native runtime is
expected to generate explicit wire `medium`, **not wire omission**. Every
outbound request must match the selected model and expected wire effort.
BCAL's own explicit-effort equality and completion guards remain unchanged.

Run preparation offline first (use a new output directory for each invocation):

```powershell
uv run python scripts\bcal_reasoning_coding.py coding `
  --config <coding-policy.json> --package <exact-net10-tools-directory> `
  --archive <exact-49019.nupkg> --symbols <local-symbol-directory> `
  --scenario <single-user-step.json> --output <new-private-output-directory>
```

Only an independently authorized smoke adds `--execute`. Execution needs the
pinned bc-eval inference dependencies and existing TEST certificate routing;
installing this entry point is not provider-call authorization. No workflow
dispatch is implied. The package must contain `bcal.exe`; this entry point is
Windows-only. No BC connection or inherited BCAL settings/provider credentials
are passed to the coding subprocess.

Auxiliary Chat is explicitly **forbidden**, not silently routed to the main
model. Its configured external command records an invocation and fails without
sending HTTP; any invocation invalidates the run even if BCAL later completes.
Reachable coding paths that need it require separate policy design/admission.
Native self-review does not itself imply an auxiliary acceptance reviewer.

Actual provider sends are reserved durably before the non-retrying innermost
HTTP transport. HTTP errors (including 429), transport/stream failures, repeated
identical requests, and policy violations stop further admission. The shared
cap counts every send, not turns or successful replies. This is a request cap,
not a provider-token or monetary ceiling. The SDK request-count option is an
additional guard, not the HTTP accounting source.

The ordinary pinned checklist scorer helper `score_checklist` adds a
single-attempt callback boundary that converts failures to a non-retriable,
sanitized exception and validates the complete checklist before scoring. This
contains the independent `autoevals.oai.run_cached_request` RateLimitError loop;
OpenAI `max_retries=0` alone does not. Its judge contract remains Ceres/Chat with
true omitted effort. Coding smoke deliberately performs **no judge scoring**.
Historical study/scoring entry points are unchanged: future gold integration
must use the bounded route and scorer together under a separately admitted
workload.

Only `receipt.json` and `provider-attempts.json` are sanitized publication
artifacts. The `private` and per-model directories contain raw inputs, console
logs, transcripts and generated AL and must not be uploaded. Successful coding requires native
runtime/source identity, unchanged completion verification, compilation covering
the latest source change, AL export, clean HTTP evidence, and zero auxiliary
invocations. A smoke success is not a quality comparison or proof of the best
reasoning setting.

The separately authorized `reasoning-coding-smoke` workflow phase runs the
same new synthetic ClampPriority codeunit task once on each of the three exact
models, sequentially, with explicit medium. `scripts\bcal_reasoning_smoke.py`
pins one 30-provider-attempt child configuration per model: 90 total, with
independent immutable ledgers and no cell retry, replacement, gold case or
judge. The global bound follows from exactly three once-only child admissions
and their innermost 30-send caps; it is not a token/spend bound. A failed model
does not authorize retrying it; a different preapproved model can still run
after cleanup and accounting verification.

Offline admission checks all 224 exact runtime files, the real packaged CLI
version, three actual packaged native-medium request shapes, and one full
`bcal.exe` first request to a loopback-only HTTP400 fixture using the normal
production prompt/tools. None of these admission requests reaches a provider.
The live phase is gated on current same-source admission and runner/hash checks.
Rerun attempts and any replacement executed workflow are rejected.

The separately authorized `reasoning-sol-smoke` phase admits only one Sol arm
of that same synthetic task, explicit medium, 30 actual provider sends total,
no auxiliary inference or judge, and no retry/replacement. It preserves the
completed three-model experiment rather than correcting its recorded result.
Its terminal diagnostics retain only known failure codes, closed runtime
terminal states and numeric/boolean counters. Exact whole-message comparisons
against fixed source constants produce message-signature categories, not
authenticated root-cause attribution; dynamic or wrapped messages remain
`unknown`. Raw error text is never published.

This synthetic local-only task uses an explicit five-archive dependency closure
from the frozen `28.0.46665.57479` cache (System, Application, Base Application,
System Application, Business Foundation), not the historical 350-file study
input. Each selected archive's bytes, nested app manifests, platform version
and transitive dependency versions are checked; exact paths/hashes are in the
admission receipt. A local exploratory 350-file admission timed out before any
provider request; that is pre-model infrastructure evidence, not a model result
or an established symbol-loading latency diagnosis.

No server argument or connection settings are supplied, so this exact package's
local-cache CLI path has no publish target or publish tool. Normal local AL
authoring, latest-source compilation and export remain required. Bounded
response observation retains usage and reasoning-token availability when
exposed, never response bodies or reasoning text. `matrix.json`, admission
proofs and the copied per-model receipts/ledgers are the sanitized workflow
outputs; the private work directory is never uploaded. Three tiny executions
can establish this coding path works, not which model or effort is best.

The separately gated `reasoning-new-sol-smoke` and `reasoning-medium-gold`
phases use only the new callback-reset package identified by the opt-in
`experiments\bcal-reasoning-gold\package.json`. Missing package identity or
actual-package reset/control delivery proofs block admission; source-built
evidence is not a substitute. Historical 49019 helpers, results and defaults
remain unchanged. The new native request helper is a separate exact-identity
copy, and all three models must generate explicit medium offline.
Final owner index/seal hashes and every referenced proof are checked offline
before producing the sanitized `owner-proof-admission.json`; live admission
binds its hash and exact package/SDK/eleven-case ownership/parity facts. Original
local artifact paths and proof bodies are not copied into that receipt.
Sealed receipt files retain their exact newline bytes through Git checkout;
their owner-bound hashes are never recomputed after text normalization.

The new Sol phase permits one execution of the same synthetic task, at most
30 actual provider HTTP attempts, no auxiliary inference or judge. Only a
same-source successful fresh compile/export receipt admits the one gold
repetition: the frozen 110 NL2AL cases, all 350 exact symbol archives, and
three models on that same package, with explicit medium. Ordinary Ceres
judging retains true omitted effort. Four coding workers and two judge
workers run concurrently; the logical SDK limits remain 64 requests and
1200 seconds per gold cell.
The hosted controller stops new sends after its five-hour job window, then
drains already running bounded children before the six-hour runner cutoff so
partial accounting can be retained. Configured per-cell SDK/process ceilings
remain unchanged; a global infrastructure stop leaves interrupted cells
unscored and never authorizes a rerun.

Each gold cell has an independent 64-coding/1-judge actual HTTP ceiling,
including failed responses and internal sends. A shared transactional SQLite
ledger enforces once-only cell admission, 21,120 coding plus 330 judge
reservations and 21,450 combined; failures do not reset it. Reservations
precede outbound sends and may conservatively exceed completed HTTP attempts
if interrupted before dispatch. Sanitized pre-send journals and the safe
SQLite ledger are retained even when a child cannot write a terminal receipt.
No retry, rejudging, replacement or additional repetition is authorized.
Provider, identity, accounting and judge failures remain unscored rather than
being silently converted to model quality failures.

Coding failures retain an allowlisted validation stage, subprocess outcome,
exit code and exception category. Route journals separately count listener,
local request, authentication and wire-validation boundaries without recording
URLs, credentials, headers, prompts or exception messages. Zero provider sends
alone do not identify a startup cause; a missing native startup stage or unknown
terminal message remains an explicit diagnostic gap. Diagnostic source changes
also change the same-SHA smoke/gold binding and never authorize a replacement.

The separate once-only `reasoning-startup-offline` diagnostic phase exercises
the same actual-package smoke command, package copy, symbols, sanitized child
environment and export scaffold without provider credentials. A synthetic
loopback HTTP400 stops the first native request without executing tools.
Before any fixture child, active Windows firewall rules deny all non-loopback
IPv4/IPv6 traffic for all programs/protocols; external-denial and loopback
control probes must pass. A parent socket guard also rejects external DNS and
connections. Rules are removed before safe artifacts upload. Failure to establish
denial stops admission, never falls back to live access. Startup error with zero
requests and successful startup reaching the deliberate400 are diagnostic
outcomes, not domain completion or replacement smoke/gold approval.

Nonpackage startup diagnostics have a separate preparation-only driver,
`scripts\bcal_nonpackage_diagnostic.py`. It requires an externally hashed
identity manifest (source, optional dirty-patch hash, CLI version, complete
file hashes/sizes and explicit SDK/native binary roles), verifies the full
runtime before and after a worker copy, and always labels it
`source-built-nonpackage` with no package or gold admission claim. It never
changes the governed package verifier or reuses a consumed hosted phase.
Native failure fields are read only from `agentRuntimeEvidence[i].failure`;
stage and exception categories must match the runtime owner's closed sets.
Unknown values fail the diagnostic gate rather than being silently dropped.
No binary staging or hosted execution is implied by preparing this driver.

The separately authorized `reasoning-nonpackage-startup-v1` phase consumes only
the exact frozen diagnostic archive from a private Azure blob. Its short-lived,
read-only HTTPS delegation URL is passed as a masked repository secret, never
as a workflow input or artifact. Archive bytes, complete inventory and three
root provenance files are verified before extraction; no runtime build or
package publication occurs. The original package phase and its once-only
history remain separate. The staging owner removes the private blob and
ephemeral repository secret immediately on terminal completion or failure and
verifies absence; URL expiration alone is not data retention enforcement.
