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
    {% assign sorted_results = site.data.bug-fix | sort: "percentage" | reverse %}
    {% for result in sorted_results %}
      {% if result.experiment == null %}
    <tr>
      <td>{{ result.agent_name }}</td>
      <td>{{ result.model }}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.percentage }}%)</td>
      <td>{% if result.average_duration %}{{ result.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/actions/runs/{{ result.github_run_id }}" target="_blank">{{ result.date }}</a></td>
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
      <th>% Resolved</th>
      <th>Avg Duration (s)</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix | sort: "percentage" | reverse %}
    {% for result in sorted_results %}
      {% if result.model == "claude-opus-4-5" and result.agent_name == "GitHub Copilot CLI" %}
        {% unless result.experiment.custom_instructions == true %}
    <tr>
      <td>{% if result.experiment.mcp_servers %}{{ result.experiment.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.percentage }}%)</td>
      <td>{% if result.average_duration %}{{ result.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/actions/runs/{{ result.github_run_id }}" target="_blank">{{ result.date }}</a></td>
    </tr>
        {% endunless %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>

Comparing experimental configurations for GitHub Copilot CLI with **claude-opus-4.5**.

<table>
  <thead>
    <tr>
      <th>MCP Servers</th>
      <th>% Resolved</th>
      <th>Avg Duration (s)</th>
      <th>Date</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.bug-fix | sort: "percentage" | reverse %}
    {% for result in sorted_results %}
      {% if result.model == "claude-opus-4-5" and result.agent_name == "GitHub Copilot CLI" %}
        {% unless result.experiment.custom_instructions == true %}
    <tr>
      <td>{% if result.experiment.mcp_servers %}{{ result.experiment.mcp_servers }}{% else %}None{% endif %}</td>
      <td>{{ result.resolved }} / {{ result.total }} ({{ result.percentage }}%)</td>
      <td>{% if result.average_duration %}{{ result.average_duration | round: 1 }}{% else %}N/A{% endif %}</td>
      <td><a href="https://github.com/microsoft/BC-Bench/actions/runs/{{ result.github_run_id }}" target="_blank">{{ result.date }}</a></td>
    </tr>
        {% endunless %}
      {% endif %}
    {% endfor %}
  </tbody>
</table>
