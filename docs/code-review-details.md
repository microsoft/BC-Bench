---
layout: default
title: Code Review Advanced Metrics - BC-Bench
---

<style>
  .main-content {
    max-width: 96rem;
  }
  .metrics-scroll {
    margin-bottom: 2rem;
    overflow-x: auto;
  }
  .metrics-scroll table {
    display: table;
    min-width: 150rem;
    width: 100%;
    white-space: nowrap;
  }
  .metrics-scroll th,
  .metrics-scroll td {
    padding: 0.35rem 0.5rem;
    text-align: right;
  }
  .metrics-scroll th:first-child,
  .metrics-scroll td:first-child,
  .metrics-scroll th:nth-child(2),
  .metrics-scroll td:nth-child(2),
  .metrics-scroll th:nth-child(3),
  .metrics-scroll td:nth-child(3) {
    text-align: left;
  }
  .metrics-scroll code {
    white-space: normal;
  }
</style>

# Code Review Advanced Metrics

This view exposes every quality, performance, configuration, and usage metric persisted in the public code-review leaderboard data. The [default leaderboard](code-review.html) keeps only the headline metrics.

Producer-only diagnostics that are not stored in `docs/_data/code-review.json` cannot be displayed here.

## Aggregate metrics

{% if site.data.code-review.aggregate and site.data.code-review.aggregate.size > 0 %}
<div class="metrics-scroll">
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>Configuration</th>
      <th>Runs</th>
      <th>Tasks</th>
      <th>Micro Precision</th>
      <th>Micro Recall</th>
      <th>Micro F1</th>
      <th>Micro F1 95% CI</th>
      <th>Micro F0.5</th>
      <th>Micro F2</th>
      <th>Macro Precision</th>
      <th>Macro Recall</th>
      <th>Macro F1</th>
      <th>Macro F1 95% CI</th>
      <th>Macro F0.5</th>
      <th>Macro F2</th>
      <th>Valid Output</th>
      <th>Avg Time</th>
      <th>Avg Prompt Tokens</th>
      <th>Avg Completion Tokens</th>
      <th>Avg Total Tokens</th>
      <th>Avg AI Credits</th>
      <th>Judge</th>
      <th>BC-Bench</th>
    </tr>
  </thead>
  <tbody>
    {% assign aggregate_results = site.data.code-review.aggregate | sort: "f1" | reverse %}
    {% for agg in aggregate_results %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{% if agg.experiment %}<code>{{ agg.experiment | jsonify }}</code>{% else %}Baseline{% endif %}</td>
      <td>{{ agg.num_runs }}</td>
      <td>{{ agg.total }}</td>
      <td>{{ agg.precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.recall | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.f1 | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.f1_ci_low != null %}{{ agg.f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.f1_ci_high | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{{ agg.f_beta_05 | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.f_beta_2 | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.macro_precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.macro_recall | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.macro_f1 | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.macro_f1_ci_low != null %}{{ agg.macro_f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.macro_f1_ci_high | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{{ agg.macro_f_beta_05 | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.macro_f_beta_2 | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.valid_review_output_rate != null %}{{ agg.valid_review_output_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td>{% if agg.average_prompt_tokens != null %}{{ agg.average_prompt_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_completion_tokens != null %}{{ agg.average_completion_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_total_tokens != null %}{{ agg.average_total_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_ai_credits != null %}{{ agg.average_ai_credits | round: 4 }}{% else %}—{% endif %}</td>
      <td>{{ agg.judge_model }}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<p><em>No aggregate results available.</em></p>
{% endif %}

## Individual run metrics

{% if site.data.code-review.runs and site.data.code-review.runs.size > 0 %}
<div class="metrics-scroll">
<table>
  <thead>
    <tr>
      <th>Run</th>
      <th>Agent</th>
      <th>Model</th>
      <th>Configuration</th>
      <th>Date</th>
      <th>Tasks</th>
      <th>Generated</th>
      <th>Expected</th>
      <th>Matched</th>
      <th>Incorrect</th>
      <th>Missed</th>
      <th>Ignored</th>
      <th>Micro Precision</th>
      <th>Micro Recall</th>
      <th>Micro F1</th>
      <th>Micro F0.5</th>
      <th>Micro F2</th>
      <th>Macro Precision</th>
      <th>Macro Recall</th>
      <th>Macro F1</th>
      <th>Macro F0.5</th>
      <th>Macro F2</th>
      <th>Severity MAE</th>
      <th>Valid Output</th>
      <th>Avg Time</th>
      <th>Avg LLM Time</th>
      <th>Avg Prompt Tokens</th>
      <th>Avg Completion Tokens</th>
      <th>Avg Total Tokens</th>
      <th>Avg AI Credits</th>
      <th>Avg Tool Usage</th>
      <th>Judge</th>
      <th>BC-Bench</th>
    </tr>
  </thead>
  <tbody>
    {% assign run_results = site.data.code-review.runs | sort: "date" | reverse %}
    {% for run in run_results %}
    <tr>
      <td>{% if run.github_run_id %}<a href="https://github.com/microsoft/BC-Bench/actions/runs/{{ run.github_run_id }}" target="_blank">{{ run.github_run_id }}</a>{% else %}—{% endif %}</td>
      <td>{{ run.agent_name }}</td>
      <td>{{ run.model }}</td>
      <td>{% if run.experiment %}<code>{{ run.experiment | jsonify }}</code>{% else %}Baseline{% endif %}</td>
      <td>{{ run.date }}</td>
      <td>{{ run.total }}</td>
      <td>{{ run.generated_comment_count }}</td>
      <td>{{ run.expected_comment_count }}</td>
      <td>{{ run.matched_comment_count }}</td>
      <td>{{ run.incorrect_comment_count }}</td>
      <td>{{ run.missed_comment_count }}</td>
      <td>{{ run.ignored_matched_comment_count }}</td>
      <td>{{ run.precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.recall | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.f1 | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.f_beta_05 | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.f_beta_2 | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.macro_precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.macro_recall | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.macro_f1 | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.macro_f_beta_05 | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.macro_f_beta_2 | times: 100.0 | round: 1 }}%</td>
      <td>{{ run.severity_mae | round: 3 }}</td>
      <td>{% if run.valid_review_output_rate != null %}{{ run.valid_review_output_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{{ run.average_duration | round: 1 }}s</td>
      <td>{% if run.average_llm_duration != null %}{{ run.average_llm_duration | round: 1 }}s{% else %}—{% endif %}</td>
      <td>{% if run.average_prompt_tokens != null %}{{ run.average_prompt_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_completion_tokens != null %}{{ run.average_completion_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_total_tokens != null %}{{ run.average_total_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_ai_credits != null %}{{ run.average_ai_credits | round: 4 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_tool_usage %}<code>{{ run.average_tool_usage | jsonify }}</code>{% else %}—{% endif %}</td>
      <td>{{ run.judge_model }}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ run.benchmark_version }}" target="_blank">{{ run.benchmark_version }}</a></td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<p><em>No individual run results available.</em></p>
{% endif %}

[← Back to Code Review](code-review.html)
