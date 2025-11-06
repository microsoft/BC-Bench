---
layout: default
title: BC-Bench
---

A benchmark for evaluating AI coding on Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Evaluation Results

<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>% Resolved</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.results | sort: "resolved" | reverse %}
    {% for result in sorted_results %}
    <tr>
      <td>{{ result.agent_name }}</td>
      <td>{{ result.model }}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.resolved | times: 100.0 | divided_by: result.total | round: 1 }}%)</td>
      <td>{{ result.date }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

For more information, visit the [BC-Bench repository](https://github.com/microsoft/BC-Bench).
