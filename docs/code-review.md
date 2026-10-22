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

The judge receives `sum((expected_in_file + ignored_in_file) * generated_in_file)` candidates. This deliberate increase in judge input avoids irreversible location-only pruning; entries without candidates need no judge call. Judge failures propagate rather than falling back to structural matches. Existing published results are not rescored by this change, and historical recall improvements must be measured rather than assumed.

`CodeReviewResult.create` requires explicit expected and ignored match lists from the caller. It only computes metrics from those established matches; it never infers matches from comment locations or invokes the judge itself.

### Severity scope and paired score views

This experiment's primary score is **Medium-aligned** for every code-review runner. Gold below Medium is excluded from the recall denominator and added to the neutral matching bucket. Unknown-severity gold remains required. Generated comments are **never filtered by their self-reported severity**: a Low or unspecified output can still earn an in-scope match, and unrelated output still counts against precision. Neutral matching remains one-to-one, so duplicate outputs cannot all hide behind a single Low gold.

The judge evaluates the full original expected/ignored candidate set **once**. The same confirmed edges produce two independent one-to-one assignments: an original all-gold assignment and a scope-aligned assignment that prioritizes in-scope expected matches over neutral matches. The latter is not computed by subtracting only historical false negatives or by discarding a generated comment before matching.

Results persist `minimum_severity`, `out_of_scope_comments`, `out_of_scope_matched_comment_count`, and the complete `unscoped_result`; run summaries and aggregates preserve `unscoped_summary` and `unscoped_aggregate`. Console/Actions reports show the floor, excluded/neutral counts and both score views; export metadata includes `scoring_scope` and `unscoped_*` metrics. Aggregation rejects mixed scopes. The unscoped view uses the **corrected current dataset** and is not a rewrite of historical scores from an older dataset. Invalid output receives no neutral credit and an entirely invalid run cannot become perfect merely because all its gold is below scope.

### Audited gold corrections

The [run 39616090167 audit dispositions](https://github.com/microsoft/BC-Bench/blob/gggdttt-benchmark-audit-repairs/dataset/audits/run-39616090167.json) preserve all 97 original missed-gold slots, their original labels, evidence, and individual repair or unresolved decisions. Four confirmed gold errors are corrected: an unsafe mandatory `ModifyAll` replacement, a public-API claim about an internal `RecordRef` helper, silent BOM persistence instead of downstream validation rejection, and an `Err` label already used by `Error`. Three source-supported functional/syntax findings are added without treating every unmatched output as correct. Source patches are unchanged.

Uncertain gold remains in place pending missing context; raw XML-doc findings filtered at the output threshold remain a severity-calibration question. Official matching remains one-to-one, including consolidated and partial-overlap findings. The audit is not a corrected precision estimate: the historical 137 completed entries yielded 105 matches out of 202 gold and 427 generated comments, while eight excluded positive entries contained another 31 gold. Removing all 23 Low gold from the frozen assignments gives only a scope-sensitivity calculation of 95/179, not 105/189 and not a new official score.

Reassessment preserves the original audit judgments while withdrawing 17 literal-message findings as confirmed reviewer omissions: the frozen BCQuality style leaf excludes mechanical compiler/standard-analyzer diagnostics. Teaching-tip sibling precedent and the external upgrade-registration/idempotency contract also remain unverified. A separate global analyzer-neutral policy is still pending; the root's ability to emit cross-cutting findings means the style-leaf exclusion alone does not settle the new malformed-syntax gold's scope. Severity alignment does not silently implement that additional policy.

Any baseline/candidate rerun must use the same corrected dataset, scorer, root/leaf/judge models, CLI, and severity thresholds. Report measurement corrections separately from reviewer improvements, retain the historical scores, and do not publish this experiment to Braintrust, Kusto, or the leaderboard before review.

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
- **Ignored** — generated comments that matched an entry's `ignored_comments` set. These are excluded from precision (they are neither correct nor incorrect); the count is surfaced for transparency only.
- **Valid output rate** — fraction of tasks whose output parsed into a structured review. Failures score zero on every other metric. (Reported per run.)
- **Micro vs. Macro** — *Micro* sums matched, scorable generated (generated minus ignored), and expected across all tasks (tasks with many comments dominate); *Macro* averages per-task scores (every task counts equally).
- **95% CI** — confidence interval bootstrapped over the per-task F1 scores, so the leaderboard reports sampling uncertainty even for a single run. The micro `F1` CI resamples runs; the `Macro F1` CI resamples tasks.

[← Back to Home](index.md)
