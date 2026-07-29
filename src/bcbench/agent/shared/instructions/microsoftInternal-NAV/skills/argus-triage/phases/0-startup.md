# Phase 0 — Startup

Verify the environment and load the issue before any reasoning begins.

## Inputs
`ISSUE_NUMBER`, `REPO` (this repo), `CODE_ROOT` (`./src`).

## Checks
1. **Local source present** — confirm `CODE_ROOT` exists and contains AL (e.g.
   `find ./src -iname 'app.json'` returns at least one result via the "search by filename"
   capability in `compatibility.md`). If absent, stop and report — feasibility cannot be
   assessed without the source.
2. **Knowledge present** — confirm
   `internal/Argus_2/skills/argus-triage/knowledge/codebase-rules/` has `*.yaml` files.

## Load the issue → `GH_REQUEST`
Using `compatibility.md`:
- Read issue metadata: number, title, body, `state`, `labels`, `author`, `type.name`,
  `createdAt`, `updatedAt`.
- List **all** comments (paginated): for each, `{ author, body, createdAt }`.

Assemble `GH_REQUEST = { metadata..., comments: [...] }`.

## Early exits
- If **any** comment body starts with `/not-accurate` (case-insensitive, leading
  whitespace allowed) → set `FailureLabel: do-nothing`,
  `FailureReason: "flagged /not-accurate"` and go to **Phase 7**.
- If the source/knowledge checks fail → stop with a clear error (do not continue).

## Output
```json
{ "Success": true, "FailureReason": "" }
```
Carry `GH_REQUEST` forward.
