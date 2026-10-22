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

Unlike the pass/fail categories, code review is scored with **Precision / Recall / F1** over the matched comments. Every same-file expected/generated pair is sent to an LLM judge before one-to-one assignment; only pairs confirmed to describe the same underlying issue are eligible. There is no line-distance threshold or top-k pruning: a nearby unrelated finding must not hide a farther semantic match. Matched comments are additionally scored on how closely the agent's **severity** classification tracks the expected severity.

A gold entry may also declare **`ignored_comments`** — legitimate-but-optional observations (out-of-scope nitpicks, maintainer-judgment calls) that should be neither required nor penalized. All same-file ignored/generated pairs are judged in the same single pass as the expected candidates, using the fixed judge model rather than the experiment model. The final joint assignment first maximizes expected matches, then ignored matches, then minimizes total line distance. Each gold and generated comment can be used at most once; equal-value duplicate comments remain distinct. An assigned ignored match is dropped from scoring entirely: it earns no recall and does not count against precision. Thus expected credit takes precedence, but equally creditable assignments preserve as much ignored neutralization as possible.

The judge receives `sum((expected_in_file + ignored_in_file) * generated_in_file)` candidates, including retained mechanical gold. This deliberate increase in judge input avoids irreversible location-only pruning; entries without candidates need no judge call. Judge failures propagate rather than falling back to structural matches. Existing published results are not rescored by this change, and historical recall improvements must be measured rather than assumed.

`CodeReviewResult.create` requires explicit expected and ignored match lists from the caller. It only computes metrics from those established matches; it never infers matches from comment locations or invokes the judge itself.

### Severity scope and paired score views

This experiment's primary score is **Medium-aligned** for every code-review runner. Gold below Medium is excluded from the recall denominator and added to the neutral matching bucket. Unknown-severity gold remains required. Generated comments are **never filtered by their self-reported severity**: a Low or unspecified output can still earn an in-scope match, and unrelated output still counts against precision. Neutral matching remains one-to-one, so duplicate outputs cannot all hide behind a single Low gold.

The judge evaluates the full expected/ignored candidate set **once**. The same confirmed edges produce two assignments: an all-severity review-finding assignment and a Medium-aligned assignment. Both prioritize one-to-one positive matches over neutral matches and exclude mechanical diagnostics. The latter is not computed by subtracting only historical false negatives or by discarding a generated comment before matching.

Results persist `minimum_severity`, `out_of_scope_comments`, `out_of_scope_matched_comment_count`, and the complete `unscoped_result`; run summaries and aggregates preserve `unscoped_summary` and `unscoped_aggregate`. Console/Actions reports show the floor, excluded/neutral counts and both score views; export metadata includes `scoring_scope` and `unscoped_*` metrics. Aggregation rejects mixed severity scopes or mechanical policies. The unscoped view uses **all severities of review findings in the corrected current dataset**, not a rewrite of historical scores or a requirement to report mechanical gold. Invalid output receives no neutral credit and an entirely invalid run cannot become perfect merely because all its gold is outside scope.

### Retained compiler/analyzer gold

`ReviewComment.kind` distinguishes `review_finding` (default), `compiler_diagnostic`, and `analyzer_diagnostic`. All records remain in `expected_comments` with their original bodies, locations, severities and articles; that collection's legacy name no longer makes every record a required positive. `diagnostic_id` records the established rule, such as `AA0216`, independently of severity. Compiler syntax errors are not mislabeled as warnings; where no compiler was executed, the diagnostic ID remains unspecified rather than invented.

Mechanical gold never enters TP/FN in either score view. An output is neutral only after a same-file semantic judge match to such gold, **not** because the output labels itself a diagnostic. Every matching mechanical output is neutral, including repeated reports of the same diagnostic. This is an explicit neutral-only capacity exception: positive, ordinary ignored, and severity-only matching retain their one-to-one contracts. Positive credit takes precedence, and each generated output is counted at most once.

Results preserve the typed `mechanical_comments`, `mechanical_matched_comment_count`, and `mechanical_diagnostics_neutral` policy identity; summaries and exported metrics retain their counts. The [full classification inventory](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/mechanical-gold-scope.json) now maps all **145 entries / 300 gold records: 56 analyzer diagnostics, 9 compiler diagnostics, and 235 retained review findings**. Of the review findings, 218 are Medium-or-higher and 17 are Low. Its original 233-record / 45-neutral snapshot remains intact; explicit current-record mappings and before/after decisions preserve reworded, reclassified and retired records rather than reusing historical indexes.

Classification relies on demonstrated standard-tool capability, not proof that the original app enabled or ran the analyzer. The bounded effective-v2 review applies AA0218 consistently to 11 ordinary page-field findings: ten Normal source fields and one FlowField cue, with no tooltip on either declaration and no evidenced structural exclusion. These are neutral, not new business findings. Cross-statement dataflow, dependency-sensitive SIFT, semantic classification and XML-doc gold are not neutralized merely because they overlap a rule name. No AL compiler/analyzer execution is claimed.

### Audited gold corrections

The [run 39616090167 audit dispositions](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/run-39616090167.json) preserve all 97 original missed-gold slots and their original decisions: **4 fixed, 17 reviewer follow-ups, 46 unresolved, 8 severity-aligned, and 22 mechanical-neutral**, with explicit subsequent wording reassessments. Initial repairs correct an unsafe mandatory `ModifyAll` replacement, a public-API claim about an internal `RecordRef` helper, silent BOM persistence instead of downstream validation rejection, and an `Err` label already used by `Error`. The later integration also retires upgrade-005's physical-table migration expectation: its actual `a29ca6a` base defines O365 Contact as Temporary and Pending under CLEAN29. No speculative replacement defect is invented.

The style-012 false-delivery-success repair is **not recovery of an original FP**: F001 was already credited against G05's commented-out-code claim. Both were Medium, not Low. The completed granularity review clarifies original G05 to describe the unperformed send and false success, retiring the later duplicate functional addition. One cause/fix therefore requires one match, not two; the historical assignment is unchanged.

The [322-comment integration ledger](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/run-39616090167-unmatched.json) preserves every original unmatched ID across 103 entries, candidate/comment hashes, both adjudication axes, evidence limitations and individual integration decisions. Effective-v2 dispositions are 80 missing-gold candidates, 5 matching/granularity, 7 duplicate, 21 mechanical, 50 severity-scope, 78 substantive false positives and 81 unresolved. The separate factual axis is 148 supported, 55 incorrect, 39 mixed and 80 unresolved; neither axis is a corrected precision score.

Of 41 concrete additions, 37 are accepted, one already exists and three are deferred. Six of 31 constrained proposals are accepted individually; 25 remain deferred. All eight XML/public-API policy proposals remain deferred. The seven mixed missing-gold cases are narrowed to supported HTTP-status/retry concerns, excluding false transport-error and unverified provider-idempotency claims. Whole-dataset checks add seven equivalent HTTP defects even where no historical candidate reported them. In total this integration adds **50 semantic findings and 19 neutral diagnostics**, reclassifies existing style-018 G01 as neutral and retires two records. Five of six gold/matching correction proposals are applied; consent-registration granularity remains explicitly deferred. All 145 source patches and base commits are unchanged by this integration.

Uncertain gold remains in place pending missing context; raw XML-doc findings filtered at the output threshold remain a severity-calibration question. Official matching remains one-to-one, including consolidated and partial-overlap findings. The audit is not a corrected precision estimate: the historical 137 completed entries yielded 105 matches out of 202 gold and 427 generated comments, while eight excluded positive entries contained another 31 gold. Removing all 23 Low gold from the frozen assignments gives only a scope-sensitivity calculation of 95/179, not 105/189 and not a new official score.

Reassessment preserves the original audit judgments while withdrawing 17 literal-message findings as confirmed reviewer omissions: the frozen BCQuality style leaf excludes mechanical compiler/standard-analyzer diagnostics. Teaching-tip sibling precedent and the external upgrade-registration/idempotency contract also remain unverified. The user separately authorized mechanical neutrality and retention of typed records, including the root-origin pure syntax finding. This global scoring decision is explicit, not inferred from a style-leaf ban.

For the **initial 45-neutral snapshot's fixed-historical-assignment sensitivity only**, mechanical and Low exclusions overlap on six gold (one matched, five missed). Their union removes 51 gold (21 matched, 30 missed), leaving **84 TP / 67 FN / 151 gold: 55.63% recall**. Existing accepted judge edges supply no additional originally-unmatched output eligible for those initial neutral buckets, leaving 322 unmatched-by-gold FP and **84/406 = 20.69% precision**. This preserved calculation predates effective-v2 and all later gold additions/removals/rewrites; it is not a projection of the current 300-record dataset, an actual corrected score, or model improvement. New/reworded gold has no frozen matching decisions.

Any baseline/candidate rerun must use the same corrected dataset, scorer, root/leaf/judge models, CLI, and severity thresholds. Report measurement corrections separately from reviewer improvements, retain the historical scores, and do not publish this experiment to Braintrust, Kusto, or the leaderboard before review.

The final engine arms share orchestration base `9607dea1c84fcf660983a5e3791dece1fb2f1623` plus the optional child-environment forwarding fix `10086e6d19f37d4e9d419480cc38aa1615ef8954`: baseline `38180ca61e4b7ad34bec1889f3c16d7d1c113a82` declares BCQuality `a4593a1b1585a0fa663efbf39ff02c60f846d851`; candidate `4b5c5ce6ccf759ffde24c4558c113601c873c75c` declares `45cbe369527bbe6d4cad0b2a877bd1d61a617cdb`. Their full engine diff changes only that knowledge ref, although baseline is not candidate's direct parent. Knowledge remains version 1.9, Microsoft-only; the candidate changes nine existing articles / 28 files, not merely the initial two articles. Both arms use root `gpt-5.6-sol`, serial leaves `gpt-5.6-luna`, judge `gpt-5.3-codex`, CLI **1.0.88**, and both severity floors **Medium**. The shared dataset SHA256 is `f30803905a7a1235688d151384490ce1f998214d614dea8ad117ed49bbcb39a4`.

The job installs exact CLI 1.0.88 in an isolated directory and puts its native executable directory first on PATH; no launcher or floating `npx` resolution is used. The installation check uses `--no-auto-update --version`. Evaluation explicitly sets `COPILOT_AUTO_UPDATE=false`, which both new engine revisions forward to their cleared child environments. **CI alone does not freeze the CLI**: with a newer cached executable present, the real environment helper selected 1.0.102-1 when the setting was absent, versus 1.0.88 in three consecutive version-only probes with `false`. Startup and observed-version/model checks remain fail-closed. The actual installer also passed a native version probe from a path containing spaces. The engine's new environment tests pass; three pre-existing schema-message assertions fail both before and after its environment fix.

Both immutable BC-Bench arm commits belong to this draft experiment PR. A future full run must set `engine-sha` **equal to the checked-in pin** to retain the existing no-publication guard; it is not an alternative BCQuality override. Use the full 145-entry corpus, not `modified-only`, with `repeat=1`: **290 entry jobs**, planning 290 root plus 5,510 serial leaf CLI processes (19 declared leaves per entry), plus at most **228** entry-level judge invocations (114 entries with expected/ignored records per arm). CLI processes are not model API calls; tool turns, retries and repairs can increase actual requests. No automatic repeat is authorized.

The audit is integrated, but **do not dispatch until the coordinator authorizes the final identities**. The baseline BCQuality revision differs from historical `b74967bc`; historical-to-candidate changes cannot isolate the effect of the candidate knowledge repairs. Workflow dispatch must resolve a branch/tag to the intended immutable Bench commit; the `git-ref` input is a tracking label, not a checkout selector. No new dispatch refs, releases or published results are created as part of this preparation.

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
