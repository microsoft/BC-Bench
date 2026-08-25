---
layout: default
title: "Report: Custom MCP servers don't load in GitHub Copilot CLI in Actions"
---

# Why custom MCP servers don't load in GitHub Copilot CLI (in Actions)

_A finding from wiring the Business Central MCP server into the BC-Bench `data-query` category._

## Symptom

With `--bc-mcp` (or any custom MCP server) enabled, the GitHub Copilot CLI agent behaved as if the
server did not exist: it never called the `bc_data_*` tools, and its own reasoning said the tools
"aren't registered in my available tool set." The MS Learn MCP server (also custom) was blocked the
same way. Only with `--log-level=debug` was the real cause visible:

```
[WARNING] Failed to fetch MCP registry policy: 403 Forbidden.
          Non-default MCP servers will be blocked until the policy can be fetched.
[ERROR]  MCP server "bcmcp"   filtered: Could not verify server against any configured registry
[ERROR]  MCP server "mslearn" filtered: Could not verify server against any configured registry
```

## Root cause

GitHub Copilot CLI enforces an **organization/enterprise MCP registry allowlist**. At startup it calls
`GET https://api.github.com/copilot/mcp_registry` to fetch that policy. If the call fails, the CLI
**fails closed** and blocks *every* non-default MCP server.

In GitHub Actions, the CLI authenticates with the workflow's built-in `GITHUB_TOKEN` — a `ghs_`
GitHub App **installation token** (the documented, PAT-less Actions setup with `copilot-requests:
write`). That endpoint **rejects installation tokens with `403`**, even though the main model /
completions path accepts the very same token. So MCP is effectively unusable in the recommended
Actions setup — and it fails **even when the org policy is "Allow all."**

This is a known, confirmed platform issue: [github/copilot-cli#4346](https://github.com/github/copilot-cli/issues/4346).

### Evidence it is the token type, not our config or the org policy

A **user** OAuth token from a member of the same org gets a clean `200` from the same endpoint:

```console
$ gh api /copilot/mcp_registry
{"mcp_registries":[{"url":"","registry_access":"allow_all","owner":{...}}, ...]}
```

Our org returns `registry_access: "allow_all"` — nothing is actually restricted. The **only** variable
is the token type: installation token -> `403`; user token -> `200`.

## What this affects

- **GitHub Copilot CLI** in Actions with `GITHUB_TOKEN` — all custom MCP servers blocked.
- **Claude Code** is **not** affected: it does not consult GitHub's MCP registry, so it loads the same
  MCP config normally. (This is why the `data-query` MCP work was validated on the Claude path first.)

## The fix

Give the Copilot CLI a **Copilot-licensed user PAT** via `COPILOT_GITHUB_TOKEN`, falling back to the
Actions token when the secret is absent (MCP stays off, but completions still work):

```yaml
# .github/workflows/copilot-evaluation.yml
env:
  COPILOT_GITHUB_TOKEN: ${{ secrets.COPILOT_CLI_TOKEN || github.token }}
```

**Operator action required:** create a repository secret `COPILOT_CLI_TOKEN` = a PAT from a
Copilot-licensed user, SSO-authorized for the org. Until then, run the `data-query` MCP evaluations on
the **Claude Code** workflow, which is unaffected.

## Takeaways

- Custom MCP servers + `GITHUB_TOKEN` in Actions do **not** work today; the failure is silent unless
  you enable debug logging.
- "Allow all" org policy is **not** sufficient — the policy fetch itself must succeed, which requires a
  user token.
- When adding an MCP-dependent category, validate on Claude Code first and treat the Copilot path as
  gated on the PAT secret.

[<- Back to Data Query](../data-query.md)
