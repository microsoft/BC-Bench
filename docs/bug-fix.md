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
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "pass_hat_1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.pass_hat_1 | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.pass_hat_3 %}{{ agg.pass_hat_3 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

## MCP Server Experimental Configurations

Comparing experimental configurations for GitHub Copilot CLI with **claude-opus-4.5**.

<table>
  <thead>
    <tr>
      <th>MCP Servers</th>
      <th>pass^1</th>
      <th>pass^3</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "pass_hat_1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.model == "claude-opus-4-5" and agg.agent_name == "GitHub Copilot" %}
        {% unless agg.experiment.custom_instructions == true %}
    <tr>
      <td>{% if agg.experiment.mcp_servers %}{{ agg.experiment.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{{ agg.pass_hat_1 | times: 100.0 | round: 1 }}%</td>
      <td>{% if agg.pass_hat_3 %}{{ agg.pass_hat_3 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}">{{ agg.benchmark_version }}</a></td>
    </tr>
        {% endunless %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>

[← Back to Home](index.md)
