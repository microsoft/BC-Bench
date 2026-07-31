# Compatibility — capabilities → host tools

extensibility-request-triage describes actions as **logical capabilities**. Resolve each to
a concrete tool on the current host. In **offline evaluation mode** the skill runs via the
**Copilot CLI** (`--allow-all-tools --allow-all-paths`) against a local checkout, so:

- There is **no live issue** → the request is read from the prompt text, and the decision is
  written to a local `triage_result.json` (never applied via `gh`).
- The **AL source** is local under the caller-supplied `CODE_ROOT` → use local file tools,
  **not** the remote GitHub API.

Detect what is available once at the start and use the first working option per capability.

## Request capabilities (offline)

| Capability | Tool |
|---|---|
| Read the request | Parse `REQUEST_TEXT` from the prompt: title, body, any follow-up comments, and current labels. There is no `gh`, no `ISSUE_NUMBER`. |
| Emit the decision | Write the result contract (`templates/result-contract.md`) as JSON to `<CODE_ROOT>/triage_result.json`. |

> The decision only ever proposes the **managed labels** listed in `shared-rules.md`; it
> never proposes touching labels you do not manage, and never edits title, body, or
> assignees. All of this is emitted into `triage_result.json` — nothing is applied.

## Code capabilities (LOCAL source under `CODE_ROOT`)

| Capability | Tool |
|---|---|
| Search by filename | `find <CODE_ROOT> -type f -iname '<File>.al'` (or the `glob` tool: `<CODE_ROOT>/**/<File>.al`) |
| Search by content | `grep -rn --include='*.al' '<pattern>' <CODE_ROOT>` (or the `grep` tool) |
| Find file in tree | same as "search by filename" — the whole tree is local |
| Read a file | `read` / `cat` on the matched `<CODE_ROOT>/...al` path (read the whole file) |
| Grep within a file | `grep -n -C3 '<pattern>' <path>` |

There is no remote code repo and no codebase token in this mode — the source is checked
out locally under `CODE_ROOT`. AL filename derivation is unchanged (CamelCase + `.Type.al`).

## Knowledge capabilities (local files under this skill)

| Capability | Tool |
|---|---|
| Read a knowledge YAML | `read` / `cat` on `knowledge/<...>.yaml` |
| Read a phase / template | `read` / `cat` on `<...>.md` |

## Sub-agent dispatch ladder (Phase 5)

Dispatch to the first available rung and announce which one you used:

1. **Named custom agent** — only if this host registers `extensibility-request-triage-codebase-analysis`
   (cloud-agent hosting). Not available under the plain Copilot CLI.
2. **Generic sub-agent** — the CLI `task` tool with a `general-purpose` agent, passing the
   Phase 5 file path and inputs. *(Preferred under Copilot CLI.)*
3. **Inline** — if no sub-agent tool is available, run Phase 5 yourself in the current
   context.

Emit: `Dispatch: Phase 5 via rung <n> (<tool>) because rungs above are <reason>.`
