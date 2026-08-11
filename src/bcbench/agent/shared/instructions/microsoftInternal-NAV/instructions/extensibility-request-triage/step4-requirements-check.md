# Step 4: Requirements Check

Validate that the request contains all required information for its type.

**Input:** `DISTILLED_REQUEST`, `GH_REQUEST`, `TYPE`, `SUBTYPE`

Read the requirement YAMLs from `TRIAGE_ROOT/input-requirements`
(`TRIAGE_ROOT = .github/instructions/extensibility-request-triage`).

**Process:**
1. Read `TRIAGE_ROOT/input-requirements/general_requirements.yaml`.
2. Read `TRIAGE_ROOT/input-requirements/{TYPE}_requirements.yaml` (replace `-` with `_` in type name).
3. If subtype exists, read `TRIAGE_ROOT/input-requirements/{TYPE}_{SUBTYPE}_requirements.yaml` if present.
4. Evaluate every requirement against the distilled request.
5. Stop immediately if a requirement has `action: agent-not-processable` or `action: reject`.
  - if requirement with `action: reject` is met, set `FailureLabel: "close"`.
6. Otherwise, collect all failures and report them together.

**Log every requirement:** `{PASS|FAIL} | {requirement_id} - {one-line summary}`

**Return JSON:**
```json
{
  "Success": true,
  "FailureLabel": "",
  "FailureReason": ""
}
```

If `Success` is `false`, set:
- `FailureLabel` to `"close"`, `"missing-info"`, or `"agent-not-processable"`.
- `FailureReason` to a consolidated explanation of all failures.
- For `FailureLabel: "close"`, include the rejection message from the matched YAML requirement.
