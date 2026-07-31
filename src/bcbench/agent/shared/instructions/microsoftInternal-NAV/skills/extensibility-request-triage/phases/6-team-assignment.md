# Phase 6 — Team assignment

Assign the responsible team from `OBJECT_LIST`. Reads local knowledge only.

## Process
1. Read `knowledge/team-configuration/team_namespace_mapping.yaml`.
2. For each object, take its `namespace` and strip the `Microsoft.` prefix.
3. Match against the mapping with **iterative fallback**: try the full namespace, then
   drop the last segment and retry, until a match is found or no segments remain.
4. Count matches per team; assign the team with the **highest** count.
5. Tie-breaker: alphabetical (`Finance` < `Integration` < `SCM`).
6. No matches at all → `Success: false`, `FailureLabel: agent-not-processable` → Phase 7.

## Output
```json
{ "Success": true, "TEAM_LABEL": "Finance", "FailureLabel": "", "FailureReason": "" }
```
