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

1. **Understand Intent:** Determine every requested change, how the changes relate to one another, and what the author wants from the complete implementation, including all existing comments. Treat a relevant, technically coherent author reply as sufficient even when brief or spread across comments. If it addresses a suggestion or warning, do not raise it again or require specific wording; if only part remains unresolved, ask only for the missing information.

2. **Identify Targets:** Determine which objects require changes and generate `OBJECT_LIST` (only objects that need modification).

3. **Locate Each Target File (local search):** For each object in `OBJECT_LIST`, find its source file path under `CODE_ROOT`.

  **Search order (keep searches scoped and cheap):**
  1. Derive `{ObjectNameCamelCase}.{ObjectType}.al` from the object name (remove spaces and special characters, apply CamelCase, append the object-type suffix — e.g. "Sales-Post" (Codeunit) → `SalesPost.Codeunit.al`, "Item Ledger Entry" (Table) → `ItemLedgerEntry.Table.al`).
  2. `glob` by filename first, e.g. `glob("<CODE_ROOT>/**/SalesPost.Codeunit.al")`. Prefer matches under the W1 layer.
  3. If glob fails, run a single targeted `grep` by object name (NOT numeric ID) for the object declaration, e.g. `grep("codeunit .* \"Sales-Post\"", "<CODE_ROOT>/**/*.al")`.
  4. Do **not** search by numeric ID and do **not** run broad unscoped `**/*.al` content scans — these are slow. If the target still cannot be identified after glob + one grep, return `agent-not-processable` and stop.

  - **Trigger missing?** Creating a new trigger is allowed.
  - **Procedure missing?** Return `missing-info`.

4. **Check Existing Implementation — quick pre-check before loading the full file.** `grep` each target file for the entity name to reveal its current declaration section (`var`, `protected var`, access modifiers, etc.). Track already implemented changes across the complete request. Set `FailureLabel: "already-implemented"` only when every requested change already exists in the exact requested form (e.g., already `protected var`). If only some changes exist, continue analyzing all remaining changes and include only changes still needed in `OBJECT_LIST` and `SUGGESTED_IMPLEMENTATION`.

5. **Read the Full File — mandatory before any rule evaluation.** If not already implemented, `read` the complete target file. All rule checks must be based on this full content — do not substitute search snippets. The file may be large; process it entirely.

6. **Expand Context — follow the call graph when it matters.** Use judgment to decide whether reading related files (callers/callees) would change feasibility or rule evaluation. Find callers with a scoped `grep` for the procedure name under `CODE_ROOT`; find callees from the calls in the already-read file, then `glob`/`read` those objects selectively. Limit depth to what is directly relevant — stop when you have enough context.

7. **Progressive Rule Evaluation:** Apply the assembled `RULES` in order to the requested change, using the full file content and the relationships between requested changes as context. A rule must NOT be raised solely because its condition already exists in the source. Rules that explicitly evaluate existing implementation, nearby alternatives, or target-source state may use the source condition they name. Short-circuit on the first blocker.

8. **Evaluate Rules:**
  - **`blockers`** — stop on first match; outcome: `auto-reject`
  - **`alternative_suggestions`** — if any unresolved suggestion matches; outcome: `missing-info`
  - **`warnings`** — if the requested change triggers any unresolved rule condition; outcome: `missing-info`
  - **`implementation`** — only if nothing matched above for any change; generate one coherent `SUGGESTED_IMPLEMENTATION` covering all remaining changes and their dependencies

  **Alternatives:** Suggest an alternative once. If the author declines it with a relevant, technically coherent explanation, log it as `SKIP` and continue evaluating the requested design; do not ask for an exception or repeat the suggestion.

  **Important:** For `warnings`, do not override the rule with personal judgment. If the requested change triggers the condition, flag it unless the author already addressed it in comments. Log an addressed warning as `PASS` or `SKIP` and never repeat the same substantive question.

  **`SUGGESTED_IMPLEMENTATION` format:** Produce an AL code snippet — not prose — showing exactly what to add or change. Include 3–5 lines of unchanged surrounding code before and after the insertion point so a developer can locate the exact position. Mark each newly added implementation line with `// NEW`. If a new publisher procedure is added, include its full definition at the end of the snippet, but do **not** mark the event signature line itself with `// NEW`.

**Log every rule:** `{PASS|FAIL|SKIP} | {rule_id} - {reason}`

**All-or-nothing multi-change behavior:** Return one combined outcome. If any requested change is blocked, reject the complete request. If any requested change requires clarification or confirmation, return `missing-info` for the complete request and list every known unresolved item together. Approve only when every requested change passes or is already implemented.

**Success constraint:** Set `Success` to `true` only when the analysis is complete and no question, confirmation, clarification, or approval is required from the requester. If any requester response is needed, set `Success` to `false` and return the appropriate `FailureLabel` and `FailureReason`.

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
