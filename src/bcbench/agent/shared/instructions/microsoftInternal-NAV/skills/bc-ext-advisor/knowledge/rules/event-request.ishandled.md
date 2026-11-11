# IsHandled Event Rules

Apply to the `ishandled` subtype, in addition to the general and event-request rules. These guardrails prevent misuse of a pattern that lets subscribers bypass base logic.

## Blockers
### Inferred IsHandled
**Trigger:** the request does not explicitly ask to bypass logic.
**Action:** Auto-reject the subtype — reclassify as `regular` and deliver a standard event. Never infer or propose IsHandled.

### Bypass of LockTable only
**Trigger:** the protected block contains only a `LockTable` call and no other logic.
**Action:** Auto-reject — IsHandled replaces business logic; it must not bypass concurrency safeguards.

### IsHandled on an existing event
**Trigger:** the request adds an IsHandled parameter to an *existing* event.
**Action:** Auto-reject — this changes the event's contract for subscribers that never expected bypass. Direct the request toward a new, separate IsHandled event.

### IsHandled at the start of OnDelete
**Trigger:** the event sits at the very beginning of an `OnDelete` trigger.
**Action:** Auto-reject — bypassing delete can orphan records. Suggest a standard `OnBeforeDelete`/`OnAfterDelete`, or `TestField`/`Error` for conditional prevention.

### Full page action bypass
**Trigger:** the request asks for IsHandled to skip the full code in a page action `OnAction` trigger.
**Action:** Auto-reject — do not add IsHandled for full page action bypass. Suggest a page extension alternative: hide the existing action and add a replacement action with the required custom behavior.

## Warnings
### Unsafe bypass block
**Trigger:** the block to be skipped has side effects other code depends on — INSERT/MODIFY/DELETE, ledger or posting entries, workflow-controlling status updates, critical validation/security/permission checks, or number-series consumption.
**Action:** Request justification — require concrete evidence for why full bypass is needed and why safer alternatives are insufficient (regular before/after event, adding parameters to an existing event, or extracting only a safe portion). If justification is weak, recommend the safer alternative.

### IsHandled inside a loop
**Trigger:** the IsHandled event is placed inside a loop.
**Action:** Suggest a regular event before the loop, after filtering — per-iteration bypass evaluation degrades performance.

### Large bypass block
**Trigger:** the IsHandled event would wrap five or more related lines.
**Action:** Suggest extracting them into a named procedure. Do not extract 1–4 lines, unrelated variables, or a block with no meaningful name.

## Alternatives
### Existing OnBefore event in the target call chain
**Trigger:** the request asks to skip a procedure or a block inside it.
**Action:** check the target procedure first, then any direct callees, for an existing `OnBefore` event that already exposes `IsHandled` or an equivalent bypass parameter. If one exists and can cover the scenario, use that event instead of proposing a new bypass event.

### After-event may suffice
**Trigger:** the logic inside `if not IsHandled then` is simple (light assignment or calculation, no branching).
**Action:** Suggest a regular after-event and confirm: is fully skipping the base logic required, or is adjusting the result afterward enough?

## Implementation guidance
- **Initialize IsHandled.** *Apply directly.* Set `IsHandled := false;` immediately before the event call; omitting it leaves the value undefined.
- **Skip-whole-procedure pattern.** *Apply directly.* When an IsHandled event can skip an entire procedure, keep any paired `OnAfter` event firing in all cases: use `if not IsHandled then begin ... end;` rather than `if IsHandled then exit;`.
