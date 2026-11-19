---
layout: default
title: Data Query - BC-Bench
---

# Data Query

This category evaluates an **agent harness and model (or MCP Host)** on its ability to **retrieve data
from a live Business Central environment** to answer a natural-language data question. It is
**execution-based** (no LLM judge): the agent reports the rows it retrieved (`answer.json`), and the
run is **resolved** when those rows match the result set of a hidden gold AL query run against the same
Cronus/Contoso demo data (values compared normalized; order ignored unless the entry is `ordered`).

The point of the category is to compare **how the data is retrieved**:

- **Baseline** — no data tooling. The agent has to reach the answer on its own (e.g. authoring an AL
  query from knowledge of the schema), which is hard on a low-resource domain language.
- **BC MCP experiment** — the agent is given Business Central's **Data Query MCP tools**
  (`bc_data_find_tables`, `bc_data_get_table_schema`, `bc_data_get_table_relations`, `bc_data_query`)
  so it can discover tables, inspect schemas and relations, and compile/run read-only AL queries
  against the live environment. The agent is isolated so the MCP endpoint is its only route to the
  data, which keeps the comparison honest.

## Baseline Leaderboard

{% if site.data.data-query.aggregate %}
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
    {% assign sorted_results = site.data.data-query.aggregate | sort: "average" | reverse %}
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

## BC MCP Experiment

Comparing runs that enable the **Business Central Data Query MCP tools** (`bc-mcp`) against the
matching no-tooling **Default** baseline for the same model.

{% if site.data.data-query.aggregate %}
{%- assign mcp_models = "" -%}
{%- for agg in site.data.data-query.aggregate -%}
  {%- if agg.experiment and agg.experiment.mcp_servers.size > 0 -%}
    {%- assign mcp_models = mcp_models | append: "|" | append: agg.model | append: "|" -%}
  {%- endif -%}
{%- endfor -%}
<table>
  <thead>
    <tr>
      <th>Model</th>
      <th>MCP Servers</th>
      <th>Skills</th>
      <th>mean (95% CI)</th>
      <th>pass^5</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {%- assign sorted_results = site.data.data-query.aggregate | sort: "average" | reverse -%}
    {%- for agg in sorted_results -%}
      {%- assign is_mcp = false -%}
      {%- assign show_row = false -%}
      {%- if agg.experiment -%}
        {%- if agg.experiment.mcp_servers.size > 0 %}{% assign is_mcp = true %}{% assign show_row = true %}{% endif -%}
      {%- else -%}
        {%- assign model_key = agg.model | prepend: "|" | append: "|" -%}
        {%- if mcp_models contains model_key %}{% assign show_row = true %}{% endif -%}
      {%- endif -%}
      {%- if show_row %}
    <tr>
      <td>{{ agg.model }}</td>
      <td>{% if is_mcp %}{{ agg.experiment.mcp_servers | join: ", " }}{% else %}<em>Default</em>{% endif %}</td>
      <td>{% if is_mcp and agg.experiment.skills_enabled %}✓{% else %}—{% endif %}</td>
      <td>{{ agg.average | times: 100.0 | round: 1 }}%{% if agg.ci_low %} ({{ agg.ci_low | times: 100.0 | round: 1 }}-{{ agg.ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{% if agg.pass_hat_5 %}{{ agg.pass_hat_5 | times: 100.0 | round: 1 }}%{% endif %}</td>
      <td>{{ agg.average_duration | round: 1 }}s</td>
      <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
    </tr>
      {%- endif -%}
    {%- endfor %}
  </tbody>
</table>
{% else %}
<p><em>No results available yet. Check back soon!</em></p>
{% endif %}

[← Back to Home](index.md)
