# Request Types and Subtypes

Classify every request into exactly one **type**, plus a **subtype** where the type defines one. Classify on intent, not on keywords alone — signals are hints, not decisions.

## event-request
Adds or modifies a publisher (integration) event so an extension can observe or influence base logic.
Signals: "event", "publisher", "subscriber", "IntegrationEvent", "OnBefore", "OnAfter".
Subtypes:
- **ishandled** — the request *explicitly* asks to bypass or skip existing base logic through an `IsHandled` (or equivalent) parameter. Classify this subtype only on an explicit request; never infer or propose it. Adding any other parameter to an existing event is not `ishandled`.
- **regular** — every other event request (default).

## request-for-external
Widens the visibility of an existing member — for example local→global, internal→public, or removing an `OnPrem` scope restriction.
Signals: "local to global", "public", "protected", "accessibility", "expose procedure", "make variable public", "remove OnPrem".
No subtypes.

## enum-request
Creates a new enum, extends an existing enum, or replaces `Option` usage with an enum.
Signals: "enum", "option", "enum value", "enumextension".
No subtypes.

## extensibility-enhancement
Any extensibility improvement that is none of the above.
Signals: "improve", "enhance", "expose", plus general extensibility gaps.
No subtypes.

## Classification rules
- Multiple *distinct* types in one request (e.g., an event and an enum) → do not draft a combined issue; ask for one request per type.
- Multiple requests of the *same* type (e.g., two events) → allowed; classify as that type.
- A pure bug with no extensibility ask → stop the flow and point to the bug process.
- A bug combined with an extensibility ask → classify as the extensibility type and address only the extensibility change.
- If the type or subtype is uncertain, state your best assessment and ask for confirmation before continuing.
