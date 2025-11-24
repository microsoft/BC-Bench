---
layout: default
title: BC-Bench
---

A benchmark for evaluating AI coding on Business Central (AL) development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Baseline Leaderboard

<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>% Resolved</th>
      <th>Avg Duration (s)</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix | sort: "resolved" | reverse %}
    {% for result in sorted_results %}
      {% if result.mcp_servers == null and result.custom_instructions == false %}
    <tr>
      <td>{{ result.agent_name }}</td>
      <td>{{ result.model }}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.resolved | times: 100.0 | divided_by: result.total | round: 1 }}%)</td>
      <td>{% if result.average_duration %}{{ result.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
      <td>{{ result.date }}</td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

## Experimental Configurations

Comparing experimental configurations against baseline for **claude-haiku-4.5**.

<table>
  <thead>
    <tr>
      <th>MCP Servers</th>
      <th>Custom Instructions</th>
      <th>% Resolved</th>
      <th>Avg Duration (s)</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix | sort: "resolved" | reverse %}
    {% for result in sorted_results %}
      {% if result.model == "claude-haiku-4.5" %}
    <tr>
      <td>{% if result.mcp_servers %}{{ result.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{% if result.custom_instructions %}Yes{% else %}No{% endif %}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.resolved | times: 100.0 | divided_by: result.total | round: 1 }}%)</td>
      <td>{% if result.average_duration %}{{ result.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
      <td>{{ result.date }}</td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

For more information, visit the [BC-Bench repository](https://github.com/microsoft/BC-Bench).
