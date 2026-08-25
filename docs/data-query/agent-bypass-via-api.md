---
layout: default
title: "Report: The agent used BC's API directly, so we hid the credentials"
---

# When the agent bypassed MCP by calling BC's API directly

_A finding from making the `data-query` category actually exercise the Business Central MCP server._

## The point of the category

`data-query` is meant to measure whether an agent can answer a Business Central data question **using
the BC MCP server's Data Query tools** as its only route to tenant data. If the agent can reach the
data another way, the benchmark measures the wrong thing.

## Symptom: the agent never used the MCP tools

Early runs "succeeded" but the transcripts showed **zero** `bc_data_query` calls. Instead the agent:

1. Read the BC connection details from its own environment — the harness exported
   `BC_SERVER_URL`, `BC_SERVER_USERNAME`, `BC_SERVER_PASSWORD` for the container.
2. Called BC's **OData `/api`** endpoint directly from a shell (`powershell`/`Invoke-WebRequest`),
   authenticating with those Basic credentials.

The tool histogram was damning — e.g. `powershell: 260` vs `bc_data_query: 1`. The agent answered
from the raw API, not the MCP server.

### A second, subtler leak: credentials on the process command line

Even after we stopped exporting the credentials into the environment, they could still leak. The MCP
configuration was passed to the CLI as **inline JSON** containing the BC `Authorization: Basic <...>`
header. That JSON sits on the launched process's command line, which the agent can read from inside
its own shell:

```powershell
Get-CimInstance Win32_Process | Select-Object CommandLine   # recovers the Basic auth header
```

So the credentials were recoverable, and BC's `/api` and `/mcp` share the same port — a credential the
agent scrapes can be replayed against `/api`.

## The fix

Two complementary changes remove every credentialed path except the MCP server:

### 1. Scrub the connection variables from the agent's environment

`agent_subprocess_env()` (`src/bcbench/agent/shared/env.py`) builds the launched agent's environment
with the BC connection variables removed — every `BC_SERVER_*` and `BC_MCP_*`, plus
`BC_CONTAINER_NAME`. The harness itself still has them (to build the MCP config and reach the
container); the **agent subprocess** does not.

### 2. A credential-free localhost MCP gateway

Instead of handing the agent an MCP config with the real `Authorization` header, the harness starts a
tiny in-process **MCP gateway** on `127.0.0.1` (`src/bcbench/agent/shared/mcp_gateway.py`) and points
the agent's MCP config at it. The gateway:

- **injects** the `Basic` auth / `Company` / `ConfigurationName` headers itself, upstream — so the
  agent's MCP config carries **no credentials** (nothing to scrape from the process command line);
- **path-restricts** to `/mcp` — every other path (notably `/api`, `/ODataV4`) returns `403`, so even
  a recovered URL cannot reach BC's REST API through the gateway.

The BC container serves `/api` and `/mcp` on the same port, so this application-layer path filter is
essential — a network firewall cannot separate them.

## Result

With the credentials removed from the environment **and** the process command line, and `/api`
unreachable through the gateway, the MCP server became the only credentialed route to BC data. Runs
then showed the agent genuinely using `bc_data_find_tables` / `bc_data_get_table_schema` /
`bc_data_query` and producing correct answers.

## Takeaway

Isolating an agent from a data source is not just "don't set an env var." Credentials leak through
**process arguments** too, and a single shared port means REST and MCP live together. The robust
pattern is a **credential-free, path-restricted proxy**: the agent holds no secret and can reach only
the intended surface.

See also: [blocking direct database access](agent-bypass-via-sql.md) — the agent's next move after the
API door was closed.

[<- Back to Data Query](../data-query.md)
