---
layout: default
title: BC-Bench
---

## Evaluation Results

The table below shows the performance of different AI coding agents on BC-Bench tasks. Results are sorted by accuracy (number of resolved tasks).

<table>
  <thead>
    <tr>
      <th>Agent (Model)</th>
      <th>Accuracy</th>
      <th>Avg Duration (s)</th>
      <th>Token Consumption</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.leaderboard | sort: "resolved" | reverse %}
    {% for result in sorted_results %}
    <tr>
      <td><strong>{{ result.agent_name }}</strong> ({{ result.model }})</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.resolved | times: 100.0 | divided_by: result.total | round: 1 }}%)</td>
      <td>{{ result.average_duration | round: 1 }}</td>
      <td>{{ result.average_prompt_tokens | round: 0 }} prompt + {{ result.average_completion_tokens | round: 0 }} completion</td>
      <td>{{ result.date }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

## About BC-Bench

TODO

For more information, visit the [BC-Bench repository](https://github.com/microsoft/BC-Bench).
