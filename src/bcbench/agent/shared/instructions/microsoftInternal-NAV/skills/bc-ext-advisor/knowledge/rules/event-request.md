# Event Request Rules

Apply to `event-request`, in addition to the general rules.

## Blockers
### Consecutive events
**Trigger:** the new event would sit immediately before or after an existing event, separated only by whitespace, comments, or variable declarations.
**Action:** Block; suggest alternative — extend the existing event by appending the new parameters instead of adding a second event.

### IntegrationEvent with IncludeSender = true
**Trigger:** the requested event sets `IncludeSender = true`.
**Action:** In codeunits, suggest an explicit `this` parameter instead. For any object type, if no justification is given, request one covering why `IncludeSender = true` is needed, why an explicit parameter cannot be used, and a concrete use case.

## Warnings
### RecordRef parameter
**Trigger:** the event signature uses a `RecordRef` parameter.
**Action:** Request clarification — RecordRef reduces type safety. Ask how it will be used, why a typed record is insufficient, and what alternatives were considered.

### xRec parameter
**Trigger:** the event signature includes `xRec`.
**Action:** Request justification — xRec behavior is context-dependent. Ask how it will be used, why `Rec` is insufficient, and confirm its behavior here is understood. `xRec` must never be declared as `var`; it must be passed by value.

### Event inside a loop
**Trigger:** a *new* event would be placed inside a loop (does not apply to adding parameters to an existing event).
**Action:** Request justification — such events fire on every iteration. Accept only if the dataset is small and bounded, subscribers are lightweight, and no location outside the loop achieves the goal.

## Alternatives
### Similar event nearby
**Trigger:** a similar event already exists at or near the requested location on the same or a related record. "Nearby" includes events inside any procedure called at that location and its direct callees — not only events that appear adjacent in the same procedure body.
**Action:** Suggest appending parameters to the existing event rather than adding a new one.

### Existing event may suffice
**Trigger:** an existing event — at the call site, inside the called procedure, or inside a procedure it calls — could plausibly satisfy the use case.
**Action:** Request clarification — confirm whether it meets the need before drafting a new event. When proposing the candidate, include all of the following: event name, procedure/trigger where it fires, where that procedure sits relative to the requested location (call site/called procedure/direct callee), key parameters it exposes (especially `var` parameters), and a one-sentence explanation of why it can satisfy or partially satisfy the scenario.

## Implementation guidance
- **Never introduce IsHandled implicitly.** *Apply directly.* Add an `IsHandled` pattern only when it is explicitly requested (indicators: "IsHandled", "bypass", "skip", "prevent execution", or clear intent to override base behavior). Otherwise deliver a regular event.
- **Adding `var` to an existing parameter is non-breaking.** *Apply directly.* Existing subscribers continue to work.
- **New parameters go at the end.** *Apply directly.* Append to the existing parameter list.
- **Temporary record parameters use a `Temp` prefix.** *Apply directly* (e.g., `TempInvtOrderTracking`).
- **Event naming.** *Apply directly.* Start or end of a procedure/trigger: `OnBefore`/`OnAfter` + name (e.g., `OnBeforePostSalesLine`). Mid-flow: `On` + name + `OnBefore`/`OnAfter` + action context (e.g., `OnPostSalesLineOnBeforeValidation`).
- **Parameter naming.** *Apply directly.* Records: table name without spaces, unabbreviated (`SalesHeader`, not `SalesHdr`). Simple types: descriptive full names (`DocumentNo`, not `DocNo`).
- **Naming ownership.** *Apply directly.* Derive event and parameter names from the anchored location and naming rules. Do not ask the user to pick or confirm names when one compliant naming is clear from context. Ask only if multiple compliant names remain and context cannot resolve them.
- **Manual binding note.** *Apply directly.* When the procedure is called from many places, note the `EventSubscriberInstance` property and manual binding.
