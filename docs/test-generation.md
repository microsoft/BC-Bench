---
layout: default
title: Test Generation - BC-Bench
---

# Test Generation

This category "reverses" the SWE-Bench workflow: instead of generating a fix, the agent generates a regression test that reproduces the issue. This evaluates Test-Driven Development (TDD) ability—writing valid, executable AL test code that fails on the buggy codebase and would pass once fixed.

## Baseline Leaderboard

{% if site.data.test-generation.aggregate %}
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Version</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.test-generation.aggregate | sort: "average" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
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

## ALTest Custom Agent

Comparing experimental configurations for GitHub Copilot CLI with `ALTest` custom agent using **claude-opus-4-5**.

<table>
  <thead>
    <tr>
      <th>Custom Agent</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.test-generation.aggregate | sort: "average" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.model == "claude-opus-4-5" and agg.agent_name == "GitHub Copilot" %}
    <tr>
      <td>{% if agg.experiment == null %}Default{% else %}{{ agg.experiment.custom_agent }}{% endif %}</td>
      <td>{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>

[← Back to Home](index.md)
