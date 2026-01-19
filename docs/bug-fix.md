---
layout: default
title: Bug Fixing - BC-Bench
---

# Bug Fixing

This category follows the [SWE-Bench](https://www.swebench.com/) methodology. The system is tasked with fixing a bug in the Business Central (AL) codebase given an issue description.

## Baseline Leaderboard

<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>pass^1</th>
      <th>pass^3</th>
      <th>pass^5</th>
      <th>Avg Duration (s)</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "pass_power_1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{% if agg.pass_power_1 %}{{ agg.pass_power_1 }} / {{ agg.total }} ({{ agg.pass_power_1 | times: 100.0 | divided_by: agg.total | round: 1 }}%){% else %}N/A{% endif %}</td>
      <td>{% if agg.pass_power_3 %}{{ agg.pass_power_3 }} / {{ agg.total }} ({{ agg.pass_power_3 | times: 100.0 | divided_by: agg.total | round: 1 }}%){% else %}N/A{% endif %}</td>
      <td>{% if agg.pass_power_5 %}{{ agg.pass_power_5 }} / {{ agg.total }} ({{ agg.pass_power_5 | times: 100.0 | divided_by: agg.total | round: 1 }}%){% else %}N/A{% endif %}</td>
      <td>{% if agg.average_duration %}{{ agg.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

## MCP Server Experimental Configurations

Comparing experimental configurations for GitHub Copilot CLI with **claude-haiku-4.5**.

<table>
  <thead>
    <tr>
      <th>MCP Servers</th>
      <th>pass^1</th>
      <th>pass^3</th>
      <th>pass^5</th>
      <th>Avg Duration (s)</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "pass_power_1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.model == "claude-haiku-4-5" and agg.agent_name == "GitHub Copilot CLI" %}
        {% unless agg.experiment.custom_instructions == true %}
    <tr>
      <td>{% if agg.experiment.mcp_servers %}{{ agg.experiment.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{% if agg.pass_power_1 %}{{ agg.pass_power_1 }} / {{ agg.total }} ({{ agg.pass_power_1 | times: 100.0 | divided_by: agg.total | round: 1 }}%){% else %}N/A{% endif %}</td>
      <td>{% if agg.pass_power_3 %}{{ agg.pass_power_3 }} / {{ agg.total }} ({{ agg.pass_power_3 | times: 100.0 | divided_by: agg.total | round: 1 }}%){% else %}N/A{% endif %}</td>
      <td>{% if agg.pass_power_5 %}{{ agg.pass_power_5 }} / {{ agg.total }} ({{ agg.pass_power_5 | times: 100.0 | divided_by: agg.total | round: 1 }}%){% else %}N/A{% endif %}</td>
      <td>{% if agg.average_duration %}{{ agg.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
    </tr>
        {% endunless %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>

[← Back to Home](index.md)
