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

Unlike the pass/fail categories, code review is scored with **Precision / Recall / F1** over the matched comments. Expected and generated comments are paired by a globally optimal (one-to-one) assignment on file and line proximity (within a configured line tolerance), and a pair is only counted as *matched* when an LLM judge confirms the two describe the same underlying issue. Matched comments are additionally scored on how closely the agent's **severity** classification tracks the expected severity.

A gold entry may also declare **`ignored_comments`** — legitimate-but-optional observations (out-of-scope nitpicks, maintainer-judgment calls) that should be neither required nor penalized. Ignored comments are structurally paired against the generated comments and validated by the same LLM judge, in a single judge pass alongside the expected comments. Any generated comment the judge confirms as an ignored match is dropped from scoring entirely: it earns no recall and does not count against precision. Expected always takes precedence, so a comment that could match both is credited as a real find; a comment that does not hold up as an expected match can still be neutralized as ignored rather than counting as a false positive. Most entries leave `ignored_comments` empty, which scores identically to before.

## Category and runners

`code-review` is the evaluation contract: it owns the dataset, structured `review.json` output, scorer, result schema, and leaderboard schema. A runner is the system under test. The same entries can be evaluated through the generic GitHub Copilot CLI and Claude Code runners, allowing direct cross-system comparisons under one scorer.

BC PR Review is a separate agent harness fixed to the `code-review` category. It runs the production BC-ALAgents review engine with BCQuality, while generic Copilot and Claude runners continue to use their own prompts and configuration:

```text
bcbench evaluate copilot <entry> --category code-review
bcbench evaluate claude <entry> --category code-review
bcbench evaluate pr-review <entry>
```

BC-ALAgents is the PR Review harness boundary. Its repo and commit are pinned with the other harnesses in `.github/actions/install-agent-harnesses`, and that engine commit owns the BCQuality version through its own configuration. Engine updates require a new BC-Bench version and must record the BC-ALAgents commit SHA in the release notes.

For an experiment, push the pipeline and/or BCQuality changes through a BC-ALAgents branch, update the action pin to that immutable commit, then run BC-Bench from the corresponding BC-Bench commit. This keeps the reproducible dependency chain BC-Bench -> BC-ALAgents -> BCQuality. A local BC-ALAgents checkout can be supplied with `--engine-path` for smoke testing.

BC PR Review records wall-clock duration, prompt/completion/total tokens, and exact AI credits. Usage values come from the engine's strictly validated schema-v1 `_run-metrics.json`, never from console transcripts. API-call details, knowledge-filter counts, token subcategories, completeness diagnostics, and producer metadata remain in that raw artifact rather than being promoted into BC-Bench result and leaderboard schemas.

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
