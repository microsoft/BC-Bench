# Request Type Classification

**Purpose:** Classify the issue into a specific extensibility request type based on keywords and intent.

## Request Types & Logic

| Type | Keywords | Sub-Types / Logic |
|------|----------|-------------------|
| **`event-request`** | "event", "publisher", "subscriber", "OnBefore", "OnAfter" | • **`ishandled`**: When the request asks for an `IsHandled` (or similar) parameter to allow skipping code. Note: Simply adding other parameters to an *existing* event is NOT `ishandled`.<br>• **`regular`**: Default. |
| **`request-for-external`** | "local to global", "public", "accessibility", "remove OnPrem" | Change scope/visibility. |
| **`enum-request`** | "enum", "option" | • **`new_enum`**: Create brand new enum.<br>• **`extend_existing_enum`**: Add to existing. |
| **`extensibility-enhancement`** | "improve", "enhance", "add" | Catch-all for other enhancements. |

## Critical Rules

1.  **IsHandled Logic**: Identify `IsHandled` sub-type if the intent is to bypass/skip existing logic using the event, regardless of whether the specific keyword is used.
2.  **Bug Handling**:
    *   If an issue describes a "bug" but explicitly requests an extensibility change (event, enum, accessibility) to resolve it, classify as that specific request type.
    *   If it is a pure bug report (unexpected behavior/error) without an extensibility request, return `Success: false` with label `agent-not-processable` and explanation.
3.  **Single Intent**: Multiple requests of the **same type** (e.g., 3 events) are allowed. If an issue contains multiple **distinct** request types (e.g., Event + Enum creation), return `Success: false` with label `missing-info` (request split) and explanation.

## Output Format
Return a JSON object:
  *   `Success`: (boolean) True if type determined, false otherwise
  *   `TYPE`: (string) Determined type.
  *   `SUBTYPE`: (string) Determined sub-types if exist.
  *   `FailureLabel`: (string) `missing-info` or `agent-not-processable` (only if `Success` is `false`)"
  *   `FailureReason`: (string) If Success is false, provide explanation
