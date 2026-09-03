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

Diagnostic averages use only tasks that reported the metric. Coverage columns show what share of tasks contributed complete token or credit telemetry.

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
      <th>Token Coverage</th>
      <th>Credit Coverage</th>
      <th>Usage Complete</th>
      <th>Avg Cached Tokens</th>
      <th>Avg Cache Creation Tokens</th>
      <th>Avg Reasoning Tokens</th>
      <th>Avg API Calls</th>
      <th>Avg Failed API Calls</th>
      <th>Avg Calls With Usage</th>
      <th>Avg Premium Requests</th>
      <th>Avg Malformed Records</th>
      <th>Avg Articles Retained</th>
      <th>Avg Articles Pruned</th>
      <th>Avg Articles Used in Findings</th>
      <th>Avg Articles Suppressed</th>
      <th>Avg Sub-skills Executed</th>
      <th>Avg Sub-skills Skipped</th>
      <th>Judge</th>
      <th>BC-Bench</th>
      <th>Copilot CLI</th>
      <th>BC-ALAgents</th>
      <th>BCQuality</th>
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
      <td>{% if agg.token_coverage_rate != null %}{{ agg.token_coverage_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{% if agg.credit_coverage_rate != null %}{{ agg.credit_coverage_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{% if agg.usage_complete_rate != null %}{{ agg.usage_complete_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{% if agg.average_cached_tokens != null %}{{ agg.average_cached_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_cache_creation_tokens != null %}{{ agg.average_cache_creation_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_reasoning_tokens != null %}{{ agg.average_reasoning_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_api_calls != null %}{{ agg.average_api_calls | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_failed_api_calls != null %}{{ agg.average_failed_api_calls | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_usage_api_calls != null %}{{ agg.average_usage_api_calls | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_premium_requests != null %}{{ agg.average_premium_requests | round: 3 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_malformed_records != null %}{{ agg.average_malformed_records | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_knowledge_files != null %}{{ agg.average_knowledge_files | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_knowledge_pruned != null %}{{ agg.average_knowledge_pruned | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_knowledge_used != null %}{{ agg.average_knowledge_used | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_knowledge_suppressed != null %}{{ agg.average_knowledge_suppressed | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_sub_skills_executed != null %}{{ agg.average_sub_skills_executed | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if agg.average_sub_skills_skipped != null %}{{ agg.average_sub_skills_skipped | round: 1 }}{% else %}—{% endif %}</td>
      <td>{{ agg.judge_model }}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a>{% if agg.benchmark_commit %} (<a href="https://github.com/microsoft/BC-Bench/commit/{{ agg.benchmark_commit }}" target="_blank">{{ agg.benchmark_commit | slice: 0, 8 }}</a>){% endif %}</td>
      <td>{% if agg.copilot_cli_version %}{{ agg.copilot_cli_version }}{% else %}—{% endif %}</td>
      <td>{% if agg.bc_alagents_commit %}<a href="https://github.com/{{ agg.bc_alagents_repository }}/commit/{{ agg.bc_alagents_commit }}" target="_blank">{{ agg.bc_alagents_commit | slice: 0, 8 }}</a>{% else %}—{% endif %}</td>
      <td>{% if agg.bcquality_commit %}<a href="https://github.com/{{ agg.bcquality_repository }}/commit/{{ agg.bcquality_commit }}" target="_blank">{{ agg.bcquality_commit | slice: 0, 8 }}</a>{% if agg.bcquality_version %} ({{ agg.bcquality_version }}){% endif %}{% else %}—{% endif %}</td>
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
      <th>Token Coverage</th>
      <th>Credit Coverage</th>
      <th>Usage Complete</th>
      <th>Avg Cached Tokens</th>
      <th>Avg Cache Creation Tokens</th>
      <th>Avg Reasoning Tokens</th>
      <th>Avg API Calls</th>
      <th>Avg Failed API Calls</th>
      <th>Avg Calls With Usage</th>
      <th>Avg Premium Requests</th>
      <th>Avg Malformed Records</th>
      <th>Avg Articles Retained</th>
      <th>Avg Articles Pruned</th>
      <th>Avg Articles Used in Findings</th>
      <th>Avg Articles Suppressed</th>
      <th>Avg Sub-skills Executed</th>
      <th>Avg Sub-skills Skipped</th>
      <th>Avg Tool Usage</th>
      <th>Judge</th>
      <th>BC-Bench</th>
      <th>Copilot CLI</th>
      <th>BC-ALAgents</th>
      <th>BCQuality</th>
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
      <td>{% if run.token_coverage_rate != null %}{{ run.token_coverage_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{% if run.credit_coverage_rate != null %}{{ run.credit_coverage_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{% if run.usage_complete_rate != null %}{{ run.usage_complete_rate | times: 100.0 | round: 1 }}%{% else %}—{% endif %}</td>
      <td>{% if run.average_cached_tokens != null %}{{ run.average_cached_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_cache_creation_tokens != null %}{{ run.average_cache_creation_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_reasoning_tokens != null %}{{ run.average_reasoning_tokens | round: 0 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_api_calls != null %}{{ run.average_api_calls | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_failed_api_calls != null %}{{ run.average_failed_api_calls | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_usage_api_calls != null %}{{ run.average_usage_api_calls | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_premium_requests != null %}{{ run.average_premium_requests | round: 3 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_malformed_records != null %}{{ run.average_malformed_records | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_knowledge_files != null %}{{ run.average_knowledge_files | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_knowledge_pruned != null %}{{ run.average_knowledge_pruned | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_knowledge_used != null %}{{ run.average_knowledge_used | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_knowledge_suppressed != null %}{{ run.average_knowledge_suppressed | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_sub_skills_executed != null %}{{ run.average_sub_skills_executed | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_sub_skills_skipped != null %}{{ run.average_sub_skills_skipped | round: 1 }}{% else %}—{% endif %}</td>
      <td>{% if run.average_tool_usage %}<code>{{ run.average_tool_usage | jsonify }}</code>{% else %}—{% endif %}</td>
      <td>{{ run.judge_model }}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ run.benchmark_version }}" target="_blank">{{ run.benchmark_version }}</a>{% if run.benchmark_commit %} (<a href="https://github.com/microsoft/BC-Bench/commit/{{ run.benchmark_commit }}" target="_blank">{{ run.benchmark_commit | slice: 0, 8 }}</a>){% endif %}</td>
      <td>{% if run.copilot_cli_version %}{{ run.copilot_cli_version }}{% else %}—{% endif %}</td>
      <td>{% if run.bc_alagents_commit %}<a href="https://github.com/{{ run.bc_alagents_repository }}/commit/{{ run.bc_alagents_commit }}" target="_blank">{{ run.bc_alagents_commit | slice: 0, 8 }}</a>{% else %}—{% endif %}</td>
      <td>{% if run.bcquality_commit %}<a href="https://github.com/{{ run.bcquality_repository }}/commit/{{ run.bcquality_commit }}" target="_blank">{{ run.bcquality_commit | slice: 0, 8 }}</a>{% if run.bcquality_version %} ({{ run.bcquality_version }}){% endif %}{% else %}—{% endif %}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
</div>
{% else %}
<p><em>No individual run results available.</em></p>
{% endif %}

[← Back to Code Review](code-review.html)
