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
      <th>MCP Servers</th>
      <th>% Resolved</th>
      <th>Avg Duration (s)</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.leaderboard | sort: "resolved" | reverse %}
    {% for result in sorted_results %}
    <tr>
      <td>{{ result.agent_name }}</td>
      <td>{{ result.model }}</td>
      <td>{% if result.mcp_servers %}{{ result.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.resolved | times: 100.0 | divided_by: result.total | round: 1 }}%)</td>
      <td>{% if result.average_duration %}{{ result.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
      <td>{{ result.date }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

For more information, visit the [BC-Bench repository](https://github.com/microsoft/BC-Bench).
