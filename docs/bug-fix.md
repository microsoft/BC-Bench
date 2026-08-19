---
layout: default
title: Bug Fixing - BC-Bench
---

# Bug Fixing

The task is test-first: the agent writes a test that reproduces the bug, then fixes it. Two
independent scores are reported. **fix** is the headline `resolved` metric and keeps its original
meaning - the reference tests pass against the agent's fix - so it stays comparable with results
published before the test-first change. **test** is scored separately: the agent's own test must
fail on the unfixed code and pass with the reference fix.

This category follows the [SWE-Bench](https://www.swebench.com/) methodology. The system is tasked with fixing a bug in the Business Central (AL) codebase given an issue description.

## Baseline Leaderboard

<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>test</th>
      <th>fix</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "average" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.test_correct_rate %}{{ agg.test_correct_rate | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.fix_correct_rate %}{{ agg.fix_correct_rate | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

## MCP Server Experimental Configurations

Comparing experimental configurations for GitHub Copilot with **claude-opus-4.6**.

<table>
  <thead>
    <tr>
      <th>MCP Servers</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix.aggregate | sort: "average" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.model == "claude-opus-4-6" and agg.agent_name == "GitHub Copilot" %}
        {% unless agg.experiment.custom_instructions == true %}
    <tr>
      <td>{% if agg.experiment.mcp_servers %}{{ agg.experiment.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
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
