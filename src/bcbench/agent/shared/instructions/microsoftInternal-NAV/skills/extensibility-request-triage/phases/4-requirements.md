# Phase 4 — Requirements check

Validate that the request contains all required information for its type. Reads local
knowledge only (`compatibility.md` knowledge capability).

## Inputs
`DISTILLED_REQUEST`, `GH_REQUEST`, `TYPE`, `SUBTYPE`.

## Process
1. Read `knowledge/input-requirements/general_requirements.yaml`.
2. Read `knowledge/input-requirements/<TYPE>_requirements.yaml` (replace `-` with `_`).
3. If a subtype-specific file exists, read
   `knowledge/input-requirements/<TYPE>_<SUBTYPE>_requirements.yaml`.
4. Evaluate **every** requirement against the distilled request.
5. **Stop immediately** if a matched requirement has `action: agent-not-processable`
   (→ that label) or `action: reject` (→ `FailureLabel: close`, and include the
   rejection message from that YAML requirement in `FailureReason`).
6. Otherwise collect **all** failures and report them together as `missing-info`.

Log every requirement: `{PASS|FAIL} | {requirement_id} - {one-line summary}`.

Any failure → go to **Phase 7**.

## Output
```json
{ "Success": true, "FailureLabel": "", "FailureReason": "" }
```
On failure set `FailureLabel` (`close` | `missing-info` | `agent-not-processable`) and a
consolidated `FailureReason`.
