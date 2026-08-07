---
layout: default
title: Data Query - BC-Bench
---

# Data Query

This category benchmarks an agent's ability to **generate Business Central AL queries** from a natural-language data question — an offline query-generation benchmark. There is **no MCP server and no live server in the loop**: the agent writes an AL query, and the query is evaluated deterministically.

Given a question, the agent authors a single AL `query` object and writes it to `query.al`. The harness then **compiles and runs both the generated query and a gold reference query** against a fixed dataset (the BC container's Contoso demo data) and compares the result sets.

## How it is scored

Data Query is **execution-based** (like bug-fix), with no LLM judge:

- **build** — the generated query compiled and ran.
- **resolved** (the headline `ResolutionRate`) — the generated query's result set **matches the gold query's**. Rows are compared by value (numbers normalized, column names/order ignored); row order is ignored unless the entry marks the question as `ordered`.

To execute a query, the harness wraps it as an API query (injecting `APIPublisher`/`APIGroup`/`APIVersion`/`EntitySetName`), publishes a throwaway app to the container, and reads the query's OData endpoint. This runs on the `GitHub-BCBench` self-hosted runner (`requires_container = True`).

> This complements the AI Test Toolkit evals in the BC platform repo: those test the **MCP server** end-to-end, while BC-Bench benchmarks **models/agents** on query generation.

## Dataset

Each entry has an `nl_prompt` (the question) and a `gold_query` (the reference AL query whose result set defines "correct"), plus `environment_setup_version` (the BC artifact) and `ordered`. See `dataset/dataquery.jsonl`.

## Running it (no local containers)

Trigger it from the GitHub **Actions** tab — the self-hosted `GitHub-BCBench` runner provisions the BC container for you (a stock **sandbox artifact with Cronus/Contoso demo data** — no special build is needed, since the query is just compiled and run):

1. Actions → **Evaluation with GitHub Copilot** (or **Evaluation with Claude Code**) → **Run workflow**.
2. Set **category** = `data-query`, pick a **model**, leave **test-run** = `true` for a quick 2-entry run.
3. The run: provisions the container → the agent writes `query.al` → the harness compiles + runs the generated and gold queries → compares result sets → `summarize-results` reports `ResolutionRate` / `BuildRate`.

`data-query` sets `requires_container = True`; its container setup **skips the repo clone** (there is no repo — the agent generates from scratch) and just stands up the sandbox container.

### Local (optional)

```bash
uv run bcbench evaluate copilot dataquery__outstanding-sales-value-by-customer-1 \
  --category data-query --container-name <bc-sandbox> --username admin --password <pw>
```

The optional `al-mcp` / `al-lsp` levers give the agent AL compiler/language-server feedback while it authors the query.

[← Back to Home](index.md)
