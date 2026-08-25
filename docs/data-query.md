---
layout: default
title: Data Query - BC-Bench
---

# Data Query

This category benchmarks an agent's ability to **answer a Business Central data question using the BC
MCP server's Data Query tools**. Given a natural-language question, the agent must retrieve the real
data from a live Business Central environment through the `bc_data_*` MCP tools and report exactly what
they return — it cannot answer from general knowledge.

The agent writes two files:

- **`answer.json`** — a JSON array of the result rows that answer the question (one object per row).
- **`query.al`** — the single AL `query` object it used to obtain the data.

> This complements the AI Test Toolkit evals in the BC platform repo: those test the **MCP server**
> end-to-end, while BC-Bench benchmarks **models/agents** on their ability to use it to answer a
> question.

## How it is scored

Data Query is **execution-based** (like bug-fix), with no LLM judge:

- **build** — the agent produced a parseable `answer.json`.
- **resolved** (the headline `ResolutionRate`) — the agent's rows **match the gold answer**. Rows are
  compared by value (numbers normalized, column names/order ignored); row order is ignored unless the
  entry marks the question as `ordered`.

The gold answer comes from each entry's baked `gold_rows` when present; otherwise the harness runs the
entry's `gold_query` live against the container and uses its result set. A gold query that does not
compile/run is treated as a harness/dataset bug and fails the run loudly (it is never the agent's
fault).

## The BC MCP tools

When `--bc-mcp` is enabled, the agent is given exactly four Business Central Data Query tools:

| Tool | Purpose | Key parameters |
| --- | --- | --- |
| `bc_data_find_tables` | Discover tables by name/concept | `searchText`, `searchMode` (`keyword`/`semantic`) |
| `bc_data_get_table_schema` | Fields of a table | `tableId`, `nameContains` |
| `bc_data_get_table_relations` | Relations/joins of a table | `tableId`, `relatedToTableIds` |
| `bc_data_query` | Compile and/or run an AL query | `queryText`, `returnData` |

The `bc-al-query-mcp` skill (`--skills`) grounds the agent in how to use them, and `--ms-learn-mcp`
gives it Microsoft Learn docs for AL query syntax.

## Isolation: the MCP server is the agent's only route to the data

Because the category measures whether the agent can answer *through the MCP tools*, the harness goes to
some length to make sure it cannot reach the data any other way. This turned out to be the hard part —
denied one route, the agent kept finding another. Three write-ups capture what happened and how it was
addressed:

- [Custom MCP servers don't load in GitHub Copilot CLI (in Actions)](data-query/mcp-in-github-copilot-cli.md)
  — a `403` on the MCP registry policy blocks all custom MCP servers when the CLI uses the Actions
  `GITHUB_TOKEN`; the fix and why the Claude path is used first.
- [The agent bypassed MCP by calling BC's API directly](data-query/agent-bypass-via-api.md) — how BC
  credentials leaked (environment **and** process command line) and the credential-free, path-restricted
  MCP gateway that closes it.
- [The agent bypassed MCP (and the API) with direct SQL](data-query/agent-bypass-via-sql.md) — the
  `docker exec ... sqlcmd` side-door, what we did about it, and the network-isolation end-state.

The mechanics: a localhost **MCP gateway** (`src/bcbench/agent/shared/mcp_gateway.py`) fronts the BC
MCP endpoint — it injects the auth headers upstream (so the agent's MCP config is credential-free),
path-restricts to `/mcp`, and warms/caches the tool catalog. `agent_subprocess_env()`
(`src/bcbench/agent/shared/env.py`) scrubs the BC connection variables from the launched agent's
environment.

## Dataset

Each entry has an `nl_prompt` (the question) and a `gold_query` (the reference AL query whose result
set defines "correct"), an optional baked `gold_rows`, plus `environment_setup_version` (the BC
artifact) and `ordered`. See `dataset/dataquery.jsonl`.

## Running it (no local containers)

Trigger it from the GitHub **Actions** tab — the self-hosted `GitHub-BCBench` runner provisions the BC
container for you (a stock **sandbox artifact with Cronus/Contoso demo data**), publishes the MCP
configuration app, and stands up the gateway:

1. Actions -> **Evaluation with Claude Code** (or **Evaluation with GitHub Copilot**) -> **Run workflow**.
2. Set **category** = `data-query`, pick a **model**, enable **bc-mcp** (and typically **ms-learn-mcp**
   and **skills**), and leave **test-run** = `true` for a quick run.
3. The run: provisions the container -> starts the credential-free MCP gateway -> the agent queries BC
   through the `bc_data_*` tools and writes `answer.json` + `query.al` -> the harness compares the
   agent's rows to the gold answer -> `summarize-results` reports `ResolutionRate` / `BuildRate`.

> **GitHub Copilot CLI note:** custom MCP servers require a Copilot-licensed user PAT in the
> `COPILOT_CLI_TOKEN` secret; without it, use the **Claude Code** workflow (unaffected). See the
> [Copilot CLI MCP report](data-query/mcp-in-github-copilot-cli.md).

`data-query` sets `requires_container = True`; its container setup **skips the repo clone** (there is
no repo — the agent answers from the live environment) and stands up the sandbox container.

[<- Back to Home](index.md)
