# Phase 0 — Startup

Verify the environment and load the request before any reasoning begins.

## Inputs
`REQUEST_TEXT` (the request from the prompt), `CODE_ROOT` (caller-supplied AL source root).

## Checks
1. **Local source present** — confirm `CODE_ROOT` exists and contains AL (e.g.
   `find <CODE_ROOT> -iname 'app.json'` returns at least one result via the "search by
   filename" capability in `compatibility.md`). If absent, stop and report — feasibility
   cannot be assessed without the source.
2. **Knowledge present** — confirm
   `knowledge/codebase-rules/` has `*.yaml` files.

## Load the request → `GH_REQUEST`
Using `compatibility.md`, parse `REQUEST_TEXT`:
- Read metadata: title, body, current labels, and any follow-up comments in the text.
- For each comment, capture `{ body }`.

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
