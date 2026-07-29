# Phase 5 — Codebase analysis  (dispatched sub-agent)

Evaluate the feasibility of the request against the **local AL source** at `CODE_ROOT`
(`./src`). The orchestrator pre-loads the rules and dispatches this phase.

## Inputs (from the dispatch prompt)
`DISTILLED_REQUEST`, `TYPE`, `SUBTYPE`, `CODE_ROOT` (`./src`), and `RULES` (the assembled
`blockers` / `alternativeSuggestions` / `warnings` / `implementation` batches — **do not
load rule files yourself**). Use the **code capabilities** in `compatibility.md` (local
file search/read).

## Core logic
1. **Understand intent** — including all comments. If a prior author reply already
   addressed a suggestion/warning, do not raise it again.
2. **Identify targets** — the objects that actually need to change → `OBJECT_LIST`.
3. **Locate each target file under `CODE_ROOT`:**
   1. Derive `{ObjectNameCamelCase}.{ObjectType}.al`.
   2. Search by filename (`find ./src -iname '<File>.al'` / glob).
   3. If none, search by procedure or object name (`grep -rn --include='*.al'`).
   4. If still none → `agent-not-processable`.
   - Missing **trigger** → creating a new trigger is allowed. Missing **procedure** →
     `missing-info`.
4. **Quick pre-check before reading the whole file** — grep the target file for the entity
   name to see its current declaration/section. If it is **already in the exact form
   requested** → `FailureLabel: already-implemented` and stop (do not read the full file or
   evaluate rules).
5. **Read the full file** — mandatory before any rule evaluation. Base all rule checks on
   complete content, not grep snippets. Process large files entirely.
6. **Expand context only when it changes the outcome** — follow callers/callees of the
   target procedure (grep `./src` for the procedure name) if feasibility depends on them.
   Limit depth; stop when you have enough.
7. **Evaluate `RULES` in order; short-circuit on the first blocker:**
   - `blockers` — first match → outcome `auto-reject`
   - `alternativeSuggestions` — any match → `missing-info`
   - `warnings` — any condition matched in code → `missing-info` (do not override with your
     own judgment; skip only if the author already addressed it)
   - `implementation` — only if nothing above matched → produce `SUGGESTED_IMPLEMENTATION`
8. **`SUGGESTED_IMPLEMENTATION`** — an AL snippet (not prose) showing exactly what to
   add/change, with 3–5 lines of unchanged surrounding code before/after the insertion
   point. Mark each newly added line `// NEW`. If adding a new publisher procedure, include
   its full definition at the end, but do not mark the event signature line itself `// NEW`.

Log every rule: `{PASS|FAIL|SKIP} | {rule_id} - {reason}`.
**Multi-change:** if any change is blocked, reject all.

## Output
```json
{
  "Success": true,
  "OBJECT_LIST": [
    { "objectType": "Codeunit", "objectName": "Sales-Post",
      "namespace": "Microsoft.Sales.Posting",
      "filePath": "src/Apps/W1/.../SalesPost.Codeunit.al" }
  ],
  "SUGGESTED_IMPLEMENTATION": "...",
  "FailureLabel": "",
  "FailureReason": ""
}
```
`filePath` is the path **relative to the repo root** (under `src/`). Map `auto-reject` to
the reject path in Phase 7; pass `already-implemented`, `missing-info`, or
`agent-not-processable` straight through.
