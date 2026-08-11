# Step 7: Finalize

Produce the labels, advisory comment, and state, then **write the decision to disk**.

**Input:** Full workflow state — `TYPE`, `TEAM_LABEL`, `FailureLabel`, `FailureReason`,
`OBJECT_LIST`, `SUGGESTED_IMPLEMENTATION`.

**Important:** Work exclusively from the workflow state. Do not fetch files, search, or call
analysis tools here — the only tool used is the file write at the end.

**Offline output:** there is no live issue. The decision is **advisory** and is recorded as
JSON only — nothing is posted, labelled, or closed on any server. A human reviews it later.

## Decision table

| Outcome | Labels | Comment template | State |
|---------|--------|-----------------|-------|
| Feasible (Success throughout, `FailureLabel` empty) | `[TEAM_LABEL, TYPE]` | `approved_{TYPE}` | open |
| Missing info | `["missing-info"]` | explain the missing items (e.g. `missing_info_requirements` / `missing_info_procedure_not_found`) | open |
| `FailureLabel: "agent-not-processable"` | `["agent-not-processable"]` | (none) | open |
| Auto-reject (blocker) | `[]` | `rejected_request` | closed |
| Already implemented | `[]` | `already_implemented` | closed |
| `FailureLabel: "close"` and reason is stale/inactive/withdrawn | `["missing-info"]` | `stale_issue_closure` | closed |
| `FailureLabel: "close"` and any other rejection reason | `[]` | `rejected_request` | closed |
| `FailureLabel: "do-nothing"` | (none) | (none) | (no change) |

Fill the chosen template from `TRIAGE_ROOT/comment-templates/comment_templates.yaml`
(`TRIAGE_ROOT = .github/instructions/extensibility-request-triage`) using the workflow state
(team, type, missing items, suggested implementation, rejection reason). If no exact
`approved_{TYPE}` template exists, generate an equivalent approval comment. Never add a
footer that names or credits the triage agent.

## Emit the result contract

Produce **exactly** this object (the `Final_Output` the evaluation reads back):

```json
{
  "Final_Output": {
    "labels_to_set": ["Finance", "event-request"],
    "comment_to_post": "Hi, ...",
    "request_state": "open",
    "failureStep": "",
    "failureReason": ""
  }
}
```

Field rules:
- **`labels_to_set`** — the complete set of *managed* labels the request should end with. May be empty (`[]`) for a rejected request.
- **`comment_to_post`** — the advisory comment body filled from the chosen template. Empty string = no comment.
- **`request_state`** — `"open"`, `"closed"`, or `""` (no recommendation, used for `do-nothing`).
- **`failureStep`** / **`failureReason`** — diagnostics for logging only; not part of the advisory comment.

## Write it

Write the object above as valid JSON to **`<CODE_ROOT>/triage_result.json`**. This is the
single artifact the evaluation reads — there is no issue to update, no label to reconcile,
and no comment to post.

Report a one-line summary: outcome, labels, comment (y/n), state.
