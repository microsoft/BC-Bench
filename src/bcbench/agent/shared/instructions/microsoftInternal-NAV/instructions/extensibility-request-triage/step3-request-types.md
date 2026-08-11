# Step 3: Request Type Classification

Classify the extensibility request into a type and subtype.

**Input:** `DISTILLED_REQUEST`

**Types and subtypes:**

| Type | Keywords | Sub-Types / Logic |
|------|----------|-------------------|
| **`event-request`** | "event", "publisher", "subscriber", "OnBefore", "OnAfter" | • **`ishandled`**: When the request asks for an `IsHandled` (or similar) parameter to allow skipping code. Note: Simply adding other parameters to an *existing* event is NOT `ishandled`.<br>• **`regular`**: Default. |
| **`request-for-external`** | "local to global", "public", "protected", "accessibility", "remove OnPrem" | Change scope/visibility. |
| **`enum-request`** | "enum", "option" | • **`new_enum`**: Create brand new enum.<br>• **`extend_existing_enum`**: Add to existing. |
| **`extensibility-enhancement`** | "improve", "enhance", "add" | Catch-all for other enhancements. |

**Classification rules:**
- `ishandled` subtype: the author wants to skip or bypass a portion of code that currently cannot be skipped. This is a semantic judgment — look at intent, not specific words.
- Multiple distinct types (e.g., event + enum) → `Success: false`, `FailureLabel: "missing-info"`, ask author to submit separate requests.
- Multiple requests of the same type (e.g., two events) → allowed, classify as that type.
- Pure bug with no extensibility request → `Success: false`, `FailureLabel: "agent-not-processable"`.
- Bug report combined with an extensibility request → classify as the extensibility type.

**Return JSON:**
```json
{
  "Success": true,
  "TYPE": "event-request",
  "SUBTYPE": "regular",
  "FailureLabel": "",
  "FailureReason": ""
}
```
