---
layout: default
title: Test Generation - BC-Bench
---

# Test Generation

This category "reverses" the SWE-Bench workflow: instead of generating a fix, the agent generates a regression test that reproduces the issue. This evaluates Test-Driven Development (TDD) ability—writing valid, executable AL test code that fails on the buggy codebase and would pass once fixed.

## Leaderboard

{% if site.data.test-generation.aggregate %}
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
    {% assign sorted_results = site.data.test-generation.aggregate | sort: "pass_hat_1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{% if agg.pass_hat_1 %}{{ agg.pass_hat_1 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.pass_hat_3 %}{{ agg.pass_hat_3 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{% if agg.average_duration %}{{ agg.average_duration | round: 1 }}{% endif %}</td>
    </tr>
      {% endif %}
    {% endfor %}
  </tbody>
</table>
{% else %}
<p><em>No results available yet. Check back soon!</em></p>
{% endif %}

[← Back to Home](index.md)
