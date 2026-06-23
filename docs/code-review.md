---
layout: default
title: Code Review - BC-Bench
---

# Code Review

This category evaluates an agent's ability to **review** a Business Central (AL) pull request. Given a diff, the agent produces structured review comments, which are scored against an expected (gold) set of findings.

Unlike the pass/fail categories, code review is scored with **Precision / Recall / F1** over the matched comments. A generated comment is counted as *matched* when it lands on the same file and line range as an expected finding (within a configured line tolerance) **and** an LLM judge confirms the two describe the same underlying issue.

## Baseline Leaderboard

{% if site.data.code-review.aggregate and site.data.code-review.aggregate.size > 0 %}
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>Precision</th>
      <th>Recall</th>
      <th>F1</th>
      <th>Fβ (β=2)</th>
      <th>Valid Output</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.code-review.aggregate | sort: "f1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.recall | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.f1 | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.f_beta_2 %}{{ agg.f_beta_2 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.valid_review_output_rate %}{{ agg.valid_review_output_rate | times: 100.0 | round: 1 }}%{% endif %}</td>
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

## How metrics are computed

- **Precision** — of the comments the agent generated, the fraction that matched an expected finding. Penalizes noisy reviews.
- **Recall** — of the expected findings, the fraction the agent caught. Penalizes missed issues.
- **F1** — harmonic mean of precision and recall; balances both equally.
- **Fβ (β=2)** — recall-leaning F-score; weights catching issues more than avoiding noise.
- **Valid output rate** — fraction of runs whose output parsed into a structured review. Failures score zero on every other metric.
- **Micro vs. Macro** — *Micro* sums matched/generated/expected across all tasks (tasks with many comments dominate); *Macro* averages per-task scores (every task counts equally).

[← Back to Home](index.md)
