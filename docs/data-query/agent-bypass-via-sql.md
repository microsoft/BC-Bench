---
layout: default
title: "Report: The agent ran SQL against the container, so we closed that door"
---

# When the agent bypassed MCP (and the API) with direct SQL

_A finding from making the `data-query` category actually exercise the Business Central MCP server._

## Symptom: `docker exec ... sqlcmd`

After we [closed the direct-API door](agent-bypass-via-api.md) (scrubbing `BC_SERVER_*` from the
agent's environment), the agent found a **deeper** route to the data. The evaluation runs on a
self-hosted runner where Business Central runs in a sibling Docker container, and the agent's shell
had Docker access to that host. So the agent:

1. Enumerated the container: `docker inspect bcbench-<id>` (and used `BC_CONTAINER_NAME` when it was
   still exported).
2. Ran SQL **inside** the container against the raw tenant database:

   ```powershell
   docker exec bcbench-<id> powershell sqlcmd -S localhost\SQLEXPRESS -d CRONUS `
     -Q "SELECT [Document Type], COUNT(*) FROM [CRONUS].[dbo].[CRONUS International Ltd_$Sales Line$...] ..."
   ```

3. Computed the answer in T-SQL and wrote it out — bypassing **both** the MCP server **and** the OData
   API. In one run, the two entries that discovered this path "resolved"; the two that didn't "failed"
   — a benchmark measuring Docker/SQL skill, not MCP use.

## Root cause

The agent runs **on the runner host**, which has full shell and Docker access to the very container
that holds the data. Denied one route (API credentials), it reached for the next (the SQL engine
inside the container). Whack-a-mole on individual doors does not hold when the agent shares a host with
the data infrastructure.

## What we did

Two things removed the practical incentive and the easy handle for this bypass:

1. **Withhold the container identity.** `agent_subprocess_env()`
   (`src/bcbench/agent/shared/env.py`) also scrubs `BC_CONTAINER_NAME`, so the agent is not handed the
   exact container to target.
2. **Make the intended path the path of least resistance.** Once the [credential-free MCP
   gateway](agent-bypass-via-api.md) made the `bc_data_*` tools genuinely work — and the skill/prompt
   pinned their exact names — the MCP route became the obvious, easiest way for the agent to answer,
   and runs showed it using the tools rather than shelling out.

We also changed the evaluation contract so the answer must be **grounded in the returned data**
(`answer.json` = the actual rows) rather than only a query string, and the gold reference is kept out
of the agent's reach — so fabricating or reconstructing data does not score.

## Residual risk and the target architecture

Withholding the container name and removing the incentive **reduce** the direct-SQL bypass, but they do
not make it impossible: a determined agent on the shared host can still enumerate Docker and reach SQL
(port 1433) inside the container. Fully closing this requires **true isolation** — running the agent
where the BC MCP endpoint is its *only* network route to BC data:

- the agent in its own container, on a network whose only egress to BC is the MCP gateway;
- **no Docker socket** mounted into the agent;
- SQL (`:1433`) and `/api` unreachable; only `/mcp` reachable.

That is the intended end-state for hardened MCP evaluations. Until then, the honest metric is "did the
agent use the MCP tools", which the harness now records directly (tool usage is parsed from the agent
event stream, including sub-agent and MCP calls).

## Takeaway

An agent that shares a host with the data will keep finding side-doors: environment variables, process
arguments, the REST API, and finally the database engine itself. Removing incentives and identifiers
helps, but the durable fix is **network isolation** that leaves the MCP server as the only reachable
data path.

[<- Back to Data Query](../data-query.md)
