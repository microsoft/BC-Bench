---
layout: default
title: Code Review - BC-Bench
---

<style>
  /* Widen this page so the leaderboard table breathes instead of cramming into the narrow column */
  .main-content {
    max-width: 96rem;
  }
  .main-content table {
    display: table;
    width: 100%;
    table-layout: auto;
  }
  .main-content table th,
  .main-content table td {
    padding: 0.4rem 0.6rem;
  }
  .leaderboard-tabs {
    display: flex;
    gap: 0.5rem;
    margin: 1rem 0;
  }
  .leaderboard-tab {
    border: 1px solid #159957;
    border-radius: 0.3rem;
    background: transparent;
    color: #117a45;
    cursor: pointer;
    font: inherit;
    padding: 0.45rem 0.9rem;
  }
  .leaderboard-tab[aria-selected="true"] {
    background: #159957;
    color: white;
  }
</style>

# Code Review

This category evaluates an agent's ability to **review** a Business Central (AL) pull request. Given a diff, the agent produces structured review comments, which are scored against an expected (gold) set of findings.

Unlike the pass/fail categories, code review is scored with **Precision / Recall / F1** over the matched comments. Expected and generated comments are paired by a globally optimal (one-to-one) assignment on file and line proximity (within a configured line tolerance), and a pair is only counted as *matched* when an LLM judge confirms the two describe the same underlying issue. Matched comments are additionally scored on how closely the agent's **severity** classification tracks the expected severity.

A gold entry may also declare **`ignored_comments`** — legitimate-but-optional observations (out-of-scope nitpicks, maintainer-judgment calls) that should be neither required nor penalized. Ignored comments are structurally paired against the generated comments and validated by the same LLM judge, in a single judge pass alongside the expected comments. Any generated comment the judge confirms as an ignored match is dropped from scoring entirely: it earns no recall and does not count against precision. Expected always takes precedence, so a comment that could match both is credited as a real find; a comment that does not hold up as an expected match can still be neutralized as ignored rather than counting as a false positive. Most entries leave `ignored_comments` empty, which scores identically to before.

## Configuring Engine Experiments

Code Review runs the production BC-ALAgents generate path. A BC-Bench experiment branch can independently select BC-ALAgents and BCQuality sources in `src/bcbench/agent/shared/config.yaml`:

```yaml
pr_review:
  engine:
    repo: microsoft/BC-ALAgents
    ref: main
    local_path: null
  bcquality:
    repo: microsoft/BCQuality
    ref: main
    local_path: null
```

`ref` accepts a branch, tag, or commit. Set either `local_path` for an unpushed local checkout; `BC_PR_REVIEW_ROOT` remains the highest-priority BC-ALAgents local override. The `run code-review` and `evaluate code-review` commands also expose `--engine-repo`, `--engine-ref`, `--engine-local-path`, and matching `--bcquality-*` options. Results record the resolved commits for both sources.

## Baseline Leaderboard

{% if site.data.code-review.aggregate and site.data.code-review.aggregate.size > 0 %}
<table>
  <thead>
    <tr>
      <th>Agent</th>
      <th>Model</th>
      <th>Micro F1 (95% CI)</th>
      <th>Precision</th>
      <th>Recall</th>
      <th>Avg Time</th>
      <th>Ver</th>
    </tr>
  </thead>
  <tbody>
    {% assign sorted_results = site.data.code-review.aggregate | sort: "f1" | reverse %}
    {% for agg in sorted_results %}
      {% if agg.experiment == null %}
    <tr>
      <td>{{ agg.agent_name }}</td>
      <td>{{ agg.model }}</td>
      <td>{{ agg.f1 | times: 100.0 | round: 1 }}%{% if agg.f1_ci_low %} ({{ agg.f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.f1_ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
      <td>{{ agg.precision | times: 100.0 | round: 1 }}%</td>
      <td>{{ agg.recall | times: 100.0 | round: 1 }}%</td>
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

## Experiment Leaderboard

Compares review-knowledge configurations for the same model (see the Baseline Leaderboard above for the plain agent):

- **Inline knowledge (pre-#8700)** — the review checklists BCApps shipped inline before adopting BCQuality, injected as custom instructions.
- **PR-review engine** — BC-ALAgents runs against a configured BCQuality revision, with performance and context-filtering metrics captured alongside review quality.

{% assign experiment_rows = site.data.code-review.aggregate | where_exp: "agg", "agg.experiment" %}
{% if experiment_rows and experiment_rows.size > 0 %}
{% assign experiment_results = experiment_rows | sort: "f1" | reverse %}
<div class="leaderboard-tabs" role="tablist" aria-label="Experiment leaderboard metrics">
  <button class="leaderboard-tab" type="button" role="tab" aria-selected="true" aria-controls="quality-leaderboard" data-target="quality-leaderboard">Quality</button>
  <button class="leaderboard-tab" type="button" role="tab" aria-selected="false" aria-controls="performance-leaderboard" data-target="performance-leaderboard">Performance</button>
</div>

<div id="quality-leaderboard" class="leaderboard-panel" role="tabpanel">
  <table>
    <thead>
      <tr>
        <th>Variant</th>
        <th>Engine / BCQuality</th>
        <th>Agent</th>
        <th>Model</th>
        <th>Micro F1 (95% CI)</th>
        <th>Macro F1 (95% CI)</th>
        <th>Precision</th>
        <th>Recall</th>
        <th>Ver</th>
      </tr>
    </thead>
    <tbody>
      {% for agg in experiment_results %}
      <tr>
        <td>{% if agg.experiment.custom_agent == "bc-review-engine" %}PR-review engine{% elsif agg.experiment.custom_instructions %}Inline knowledge (pre-#8700){% else %}Other{% endif %}</td>
        <td>
          {% if agg.experiment.custom_agent == "bc-review-engine" and agg.experiment.plugins %}
            {% for plugin in agg.experiment.plugins %}
              {% assign plugin_parts = plugin | split: "@" %}
              {% if plugin contains "bc-review-engine@" or plugin contains "BCQuality@" %}{{ plugin_parts[0] }}@{{ plugin_parts[1] | slice: 0, 7 }}{% unless forloop.last %}<br>{% endunless %}{% endif %}
            {% endfor %}
          {% elsif agg.experiment.custom_agent == "bc-review-engine" or agg.experiment.custom_instructions %}self-contained
          {% else %}—{% endif %}
        </td>
        <td>{{ agg.agent_name }}</td>
        <td>{{ agg.model }}</td>
        <td>{{ agg.f1 | times: 100.0 | round: 1 }}%{% if agg.f1_ci_low %} ({{ agg.f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.f1_ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
        <td>{{ agg.macro_f1 | times: 100.0 | round: 1 }}%{% if agg.macro_f1_ci_low %} ({{ agg.macro_f1_ci_low | times: 100.0 | round: 1 }}-{{ agg.macro_f1_ci_high | times: 100.0 | round: 1 }}%){% endif %}</td>
        <td>{{ agg.precision | times: 100.0 | round: 1 }}%</td>
        <td>{{ agg.recall | times: 100.0 | round: 1 }}%</td>
        <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<div id="performance-leaderboard" class="leaderboard-panel" role="tabpanel" hidden>
  <table>
    <thead>
      <tr>
        <th>Variant</th>
        <th>Engine / BCQuality</th>
        <th>Agent</th>
        <th>Model</th>
        <th>Avg Time</th>
        <th>Avg Tokens</th>
        <th>API Calls</th>
        <th>Est. Credits</th>
        <th>Knowledge Used</th>
        <th>Knowledge Pruned</th>
        <th>Ver</th>
      </tr>
    </thead>
    <tbody>
      {% for agg in experiment_results %}
      <tr>
        <td>{% if agg.experiment.custom_agent == "bc-review-engine" %}PR-review engine{% elsif agg.experiment.custom_instructions %}Inline knowledge (pre-#8700){% else %}Other{% endif %}</td>
        <td>
          {% if agg.experiment.custom_agent == "bc-review-engine" and agg.experiment.plugins %}
            {% for plugin in agg.experiment.plugins %}
              {% assign plugin_parts = plugin | split: "@" %}
              {% if plugin contains "bc-review-engine@" or plugin contains "BCQuality@" %}{{ plugin_parts[0] }}@{{ plugin_parts[1] | slice: 0, 7 }}{% unless forloop.last %}<br>{% endunless %}{% endif %}
            {% endfor %}
          {% elsif agg.experiment.custom_agent == "bc-review-engine" or agg.experiment.custom_instructions %}self-contained
          {% else %}—{% endif %}
        </td>
        <td>{{ agg.agent_name }}</td>
        <td>{{ agg.model }}</td>
        <td>{{ agg.average_duration | round: 1 }}s</td>
        <td>{% if agg.average_total_tokens %}{{ agg.average_total_tokens | round: 0 }}{% else %}—{% endif %}</td>
        <td>{% if agg.average_api_calls %}{{ agg.average_api_calls | round: 1 }}{% else %}—{% endif %}</td>
        <td>{% if agg.average_estimated_credits %}{{ agg.average_estimated_credits | round: 4 }}{% else %}—{% endif %}</td>
        <td>{% if agg.average_knowledge_used %}{{ agg.average_knowledge_used | round: 1 }}{% else %}—{% endif %}</td>
        <td>{% if agg.average_knowledge_pruned %}{{ agg.average_knowledge_pruned | round: 1 }}{% else %}—{% endif %}</td>
        <td><a href="https://github.com/microsoft/BC-Bench/releases/tag/v{{ agg.benchmark_version }}" target="_blank">{{ agg.benchmark_version }}</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

<script>
  document.querySelectorAll(".leaderboard-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".leaderboard-tab").forEach((item) => item.setAttribute("aria-selected", String(item === tab)));
      document.querySelectorAll(".leaderboard-panel").forEach((panel) => {
        panel.hidden = panel.id !== tab.dataset.target;
      });
    });
  });
</script>
{% else %}
<p><em>No experiment results available yet. Check back soon!</em></p>
{% endif %}

## How metrics are computed

- **Precision** — of the scorable comments the agent generated (generated minus ignored), the fraction that matched an expected finding. Penalizes noisy reviews.
- **Recall** — of the expected findings, the fraction the agent caught. Penalizes missed issues.
- **F1** — harmonic mean of precision and recall; balances both equally (the β=1 case of Fβ).
- **Fβ (β=0.5)** — precision-leaning F-score; use when false positives are costly (noisy reviews waste reviewer time).
- **Fβ (β=2)** — recall-leaning F-score; weights catching issues more than avoiding noise.
- **Severity MAE** — mean absolute error between the agent's and the expected severity levels, over matched comments only. Lower is better; `0` means every matched comment got the severity exactly right.
- **Ignored** — generated comments that matched an entry's `ignored_comments` set. These are excluded from precision (they are neither correct nor incorrect); the count is surfaced for transparency only.
- **Valid output rate** — fraction of tasks whose output parsed into a structured review. Failures score zero on every other metric. (Reported per run.)
- **Micro vs. Macro** — *Micro* sums matched, scorable generated (generated minus ignored), and expected across all tasks (tasks with many comments dominate); *Macro* averages per-task scores (every task counts equally).
- **95% CI** — confidence interval bootstrapped over the per-task F1 scores, so the leaderboard reports sampling uncertainty even for a single run. The micro `F1` CI resamples runs; the `Macro F1` CI resamples tasks.
- **Avg Tokens / API Calls / Estimated Credits** — mean PR-review engine usage per evaluated entry. Estimated credits use the engine's configured token prices and are not a currency value.
- **Knowledge Used** — mean number of BCQuality knowledge articles remaining after filtering and available to the reviewer.
- **Knowledge Pruned** — mean number of BCQuality knowledge articles removed by the engine's filtering step before review.

[← Back to Home](index.md)
