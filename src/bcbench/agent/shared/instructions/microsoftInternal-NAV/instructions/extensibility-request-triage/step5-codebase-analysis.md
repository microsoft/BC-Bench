# Step 5: Codebase Analysis

Evaluate the feasibility of the extensibility request against the **local** AL source.

**Input:** `DISTILLED_REQUEST`, `TYPE`, `SUBTYPE`, `CODE_ROOT`

**Offline note:** the source is checked out locally under `CODE_ROOT`. Use local file tools
(`glob`, `grep`, `read`/`view`) — there is no remote GitHub API and no `github_*` tool.
Load the rule files yourself (below) from `TRIAGE_ROOT/codebase-rules`
(`TRIAGE_ROOT = .github/instructions/extensibility-request-triage`).

## Load the rules first

For each category (`blockers`, `alternative_suggestions`, `warnings`, `implementation`),
collect the following files in order, skipping any that do not exist, and assemble the
`RULES` batches:
- `TRIAGE_ROOT/codebase-rules/general_<category>.yaml`
- `TRIAGE_ROOT/codebase-rules/<typePrefix>_<category>.yaml`
- `TRIAGE_ROOT/codebase-rules/<typePrefix><subtypeSuffix>_<category>.yaml`

`typePrefix`: `event-request→event_request`, `request-for-external→request_for_external`,
`enum-request→enum_request`, `extensibility-enhancement→extensibility_enhancement`.
`subtypeSuffix`: `ishandled→_ishandled`, `new_enum→_new_enum`,
`extend_existing_enum→_extend_existing_enum`, `regular→` (none).

## Core Logic

1. **Understand Intent:** Determine what the author wants, including all existing comments. If a prior author reply already addresses a suggestion or warning, do not raise it again.

2. **Identify Targets:** Determine which objects require changes and generate `OBJECT_LIST` (only objects that need modification).

3. **Locate Each Target File (local search):** For each object in `OBJECT_LIST`, find its source file path under `CODE_ROOT`.

  **Search order (keep searches scoped and cheap):**
  1. Derive `{ObjectNameCamelCase}.{ObjectType}.al` from the object name (remove spaces and special characters, apply CamelCase, append the object-type suffix — e.g. "Sales-Post" (Codeunit) → `SalesPost.Codeunit.al`, "Item Ledger Entry" (Table) → `ItemLedgerEntry.Table.al`).
  2. `glob` by filename first, e.g. `glob("<CODE_ROOT>/**/SalesPost.Codeunit.al")`. Prefer matches under the W1 layer.
  3. If glob fails, run a single targeted `grep` by object name (NOT numeric ID) for the object declaration, e.g. `grep("codeunit .* \"Sales-Post\"", "<CODE_ROOT>/**/*.al")`.
  4. Do **not** search by numeric ID and do **not** run broad unscoped `**/*.al` content scans — these are slow. If the target still cannot be identified after glob + one grep, return `agent-not-processable` and stop.

  - **Trigger missing?** Creating a new trigger is allowed.
  - **Procedure missing?** Return `missing-info`.

4. **Check Existing Implementation — quick pre-check before loading the full file.** `grep` the target file for the entity name to reveal its current declaration section (`var`, `protected var`, access modifiers, etc.). If the entity is **already in the exact form requested** (e.g., already `protected var`), set `FailureLabel: "already-implemented"` and stop — do not load the full file or evaluate rules.

5. **Read the Full File — mandatory before any rule evaluation.** If not already implemented, `read` the complete target file. All rule checks must be based on this full content — do not substitute search snippets. The file may be large; process it entirely.

6. **Expand Context — follow the call graph when it matters.** Use judgment to decide whether reading related files (callers/callees) would change feasibility or rule evaluation. Find callers with a scoped `grep` for the procedure name under `CODE_ROOT`; find callees from the calls in the already-read file, then `glob`/`read` those objects selectively. Limit depth to what is directly relevant — stop when you have enough context.

7. **Progressive Rule Evaluation:** Apply the assembled `RULES` in order against the full file content. Short-circuit on the first blocker.

8. **Evaluate Rules:**
  - **`blockers`** — stop on first match; outcome: `auto-reject`
  - **`alternative_suggestions`** — if any match; outcome: `missing-info`
  - **`warnings`** — if any rule condition matches in code; outcome: `missing-info`
  - **`implementation`** — only if nothing matched above; generate `SUGGESTED_IMPLEMENTATION`

  **Important:** For `warnings`, do not override the rule with personal judgment. If the condition matches, flag it unless the author already addressed it in comments.

  **`SUGGESTED_IMPLEMENTATION` format:** Produce an AL code snippet — not prose — showing exactly what to add or change. Include 3–5 lines of unchanged surrounding code before and after the insertion point so a developer can locate the exact position. Mark each newly added implementation line with `// NEW`. If a new publisher procedure is added, include its full definition at the end of the snippet, but do **not** mark the event signature line itself with `// NEW`.

**Log every rule:** `{PASS|FAIL|SKIP} | {rule_id} - {reason}`

**Multi-change:** If the request contains multiple changes and ANY is blocked, reject all.

**Return JSON:**
```json
{
  "Success": true,
  "OBJECT_LIST": [
    {
      "objectType": "Codeunit",
      "objectName": "Sales-Post",
      "namespace": "Microsoft.Sales.Posting",
      "filePath": "App/Layers/W1/BaseApp/Sales/Posting/SalesPost.Codeunit.al"
    }
  ],
  "SUGGESTED_IMPLEMENTATION": "...",
  "FailureLabel": "",
  "FailureReason": ""
}
```
