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

BC PR Review requires explicit root and leaf models plus deterministic `serial` or bounded `parallel` leaf scheduling. BC-Bench pins only BC-ALAgents; that pinned engine revision owns and resolves its BCQuality dependency. Before scoring, BC-Bench validates the engine's `_run-manifest.json` against the immutable BC-ALAgents commit, pinned Copilot CLI version, resolved scheduling configuration, ordered leaf plan, requested and observed models, process completion, and complete per-process telemetry. The BCQuality revision must be present as engine-produced provenance, but BC-Bench does not select or override it. A mismatched, substituted, reordered, incomplete, or malformed run is rejected rather than included in benchmark results.

A `partial` engine manifest is a valid production recovery outcome, but not a complete benchmark observation. BC-Bench recognizes it so diagnostics remain clear, then rejects it from scored results alongside failed and incomplete manifests.

Manifest completion alone is insufficient: the original leaf and root reports must exist, match their declared roles and the pinned BCQuality schema, and preserve every ordered leaf outcome in the root. Failed or partial original reports, missing leaves, nested delegation, and root-only fields on leaf reports are rejected before the gold judge runs. Inactive leaves may report `not-applicable` or `no-knowledge` without findings; these are not evidence of a successful target suppression.

Experimental common-support integration also accepts the optional `processes[].normalization` audit record from [BC-ALAgents PR 80](https://github.com/microsoft/BC-ALAgents/pull/80) at `4a0885e207cf96617b33d54d0146debbcf7d9841`, without changing any engine pin. Only completed leaf processes may carry it; no-op and legacy records omit it rather than storing `null`. Strict typed `finding-id` and `location-range` changes retain zero-based finding indices, original/canonical IDs, and original range endpoints. Unknown fields, malformed values, duplicate kind/index pairs, unchanged IDs, and ranges not satisfying `start-line < line <= end-line` are rejected. No article-ID pattern, contiguous-index requirement, or extra change-order rule is imposed.

The engine's accepted reports at `report_path` are still validated, and `al-code-review-findings.json` remains the adapter's scoring input; normalization metadata is retained in the manifest, not applied again or promoted into gold/scoring fields. Diagnostics additionally allowlist `_review-report.raw.json` and `_review-source-bounds.json` alongside the accepted reports and manifest. The raw report path and lowercase SHA256 identify the engine-preserved original bytes for audit; manifest loading validates their shape, not the file contents or source bounds. This support layer does not make the old smoke a completed benchmark observation or authorize a new run.

Generic Copilot evaluations use the action's default CLI pin. PR Review deliberately overrides that pin to the Copilot CLI version whose OpenTelemetry version field the pinned engine validates; update the engine and this paired CLI version together only after an evaluation-identity smoke run succeeds.

For the experimental CLI `1.0.88` pairing, the engine requires an exact startup version probe but permits absent `cli_version` in OTel. The adapter accepts that documented absence only for `1.0.88`, preserves the telemetry `null`, and still rejects every nonempty conflicting version. Read `_run-manifest.json.configuration.copilot_cli_version` as startup provenance, not as an observed OTel field.

BC PR Review records wall-clock duration, prompt/completion/total tokens, and exact AI credits. Usage values come from the engine's strictly validated schema-v1 `_run-metrics.json`, never from console transcripts. The validated manifest also records the leaf model, scheduling mode, maximum concurrency, BCQuality revision and source snapshot, and process count on every result. API-call details, knowledge-filter counts, token subcategories, completeness diagnostics, and producer metadata remain in the raw artifacts rather than being promoted into leaderboard schemas.

Unavailable AI credits remain `null` in bceval exports; observed zero remains zero. The pinned bc-eval 0.3.14 consumer requires numeric prompt/completion tokens, so its existing zero fallbacks for missing tokens remain unchanged. Use the original per-entry result metrics, not bceval token fields, to distinguish unknown usage from measured zero.

The revised HTTP optional-return A/B preparation uses seven entries: three unchanged historical target entries (`synthetic__privacy-008`, `synthetic__privacy-015`, `synthetic__security-clean-02`), the existing `synthetic__errh-tryfunction-swallowed-01` positive control, and three experimental HTTP controls. `synthetic__privacy-010` is excluded from this experiment's input, not removed or changed in the dataset. The four retained historical assertions and the clean control's two bare GET/Post call sites form six distinct target sites. The consumed-false positive control puts the conditional and incorrect success return on one source line; the successful-exchange path still checks HTTP status. Syntax and structural checks are not AL compilation, and these controls are accepted for experimental use only, not official gold. Their HTTP articles remain unannotated because those articles do not exist at the pre-196 baseline. All 145 original rows remain unchanged.

The prior eight-entry smoke and its stopped receipt are a separate immutable observation, not a completed pair or reusable v2 baseline. V2 requires a new paid approval: first one paired smoke (14 entry generations, at most 280 reviewer processes and 10 gold-judge calls); five further pairs require another approval. Baseline eligibility requires valid reports, all three positive controls, and at least one of the six target misreads. Report the historical and controlled sites separately; absence at both controlled sites alone does not stop a baseline that reproduces a historical target. Candidate acceptance requires no target or mixed assertion at any of the six sites in the leaf, root or normalized output, with all positive controls retained. Any invalid report, missing baseline signal or control failure stops the experiment without retry.

Focused A/B runs require an explicit `entries` array, `test-run=true`, `modified-only=false`, `repeat=1`, and an explicit `engine-sha` equal to that arm's declared action pin. This selects the exact matrix, disables requeue and ephemeral tags, and makes summary `mock=true`: the existing gold judge and reviewer still run, but Braintrust/Kusto storage arguments and leaderboard writes are disabled. Preparation is not permission to dispatch. The diagnostic upload is a filename allowlist; download results and logs promptly (test results expire after one day, diagnostic artifacts after seven). Raw OTel is deleted by the engine after ingestion and is not promised by these artifacts.

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
