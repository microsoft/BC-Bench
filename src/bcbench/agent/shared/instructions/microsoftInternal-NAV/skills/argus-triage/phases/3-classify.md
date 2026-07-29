# Phase 3 — Request type classification

Classify `DISTILLED_REQUEST` into a `TYPE` and `SUBTYPE`. No external tools.

## Types and subtypes
| Type | Signals | Subtypes / logic |
|------|---------|------------------|
| `event-request` | "event", "publisher", "subscriber", "OnBefore", "OnAfter" | **`ishandled`**: asks for an `IsHandled`-style parameter to allow skipping code (semantic — judge intent, not keywords; adding *other* params to an existing event is **not** ishandled). **`regular`**: default. |
| `request-for-external` | "local to global", "public", "protected", "accessibility", "remove OnPrem" | scope/visibility change |
| `enum-request` | "enum", "option" | **`new_enum`** (create new) / **`extend_existing_enum`** (add to existing) |
| `extensibility-enhancement` | "improve", "enhance", "add" | catch-all |

## Rules
- Multiple **distinct** types (e.g. event + enum) → `Success: false`,
  `FailureLabel: missing-info`, ask the author to file separate issues.
- Multiple requests of the **same** type → allowed; classify as that type.
- Pure bug, no extensibility ask → `Success: false`, `FailureLabel: agent-not-processable`.
- Bug report **combined with** an extensibility request → classify as the extensibility type.

Any failure → go to **Phase 7**.

## Output
```json
{ "Success": true, "TYPE": "event-request", "SUBTYPE": "regular", "FailureLabel": "", "FailureReason": "" }
```
