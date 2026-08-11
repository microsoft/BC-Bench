# Step 6: Team Assignment

Assign the responsible team based on the objects in `OBJECT_LIST`.

**Input:** `OBJECT_LIST`

**Process:**
1. Read `TRIAGE_ROOT/team-configuration/team_namespace_mapping.yaml`
   (`TRIAGE_ROOT = .github/instructions/extensibility-request-triage`).
2. For each object, extract its namespace and strip the `Microsoft.` prefix.
3. Match the namespace against the mapping using iterative fallback: try the full namespace, then remove the last segment and retry, until a match is found or no segments remain.
4. Count matches per team. Assign the team with the highest count.
5. Tie-breaker: alphabetical order (Finance before Integration before SCM).
6. No matches at all → `Success: false`, `FailureLabel: "agent-not-processable"`.

**Return JSON:**
```json
{
  "Success": true,
  "TEAM_LABEL": "Finance",
  "FailureLabel": "",
  "FailureReason": ""
}
```
