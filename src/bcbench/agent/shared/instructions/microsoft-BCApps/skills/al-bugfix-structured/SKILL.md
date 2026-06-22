---
name: al-bugfix-structured
description: Structural best-practice guidance for fixing bugs in Microsoft Dynamics 365 Business Central (AL) code. Use this when fixing an AL issue or implementing an AL code change in Business Central, to avoid common cross-layer failure modes (validation semantics, event/trigger placement, workflow completeness, object availability, syntax).
---

When fixing an AL bug in Business Central, apply the guidance for every layer that
is relevant to the change. The bullets are ordered from most fundamental to most
ecosystem-dependent; a fix that respects all applicable layers is far more likely
to be correct.

## L1 - Syntax / Representation

- Produce valid AL: correct `trigger` declarations and procedure signatures,
  balanced `begin`/`end` blocks, and object identifiers of at most 30 characters.
- Match member names, types, and parameter lists exactly to the declarations.

## L2 - Execution / Validation Semantics

- When a field change must run its validation logic, set it with
  `Rec.Validate("Field", Value)` rather than a direct `Rec."Field" := Value`
  assignment.
- Respect the validation and modification order; call `TestField` before a state
  transition that requires the field to be set.
- Check the return value of `Get`/`Find*` before using the record.

## L3 - Event-Driven Paradigm

- Put the logic in the CORRECT trigger or event, and keep it there: e.g. field
  validation belongs in `OnValidate`, not relocated into a later processing flow.
- Prefer subscribing to a published event (`[EventSubscriber]`) over directly
  modifying a core/base object when extending behaviour.
- Respect trigger responsibility: do not persist or compute state from a trigger
  (e.g. `OnModify`) when the intended owner is a page/workflow step, or vice versa.

## L4 - Workflow / Business-Logic Composition

- Implement the COMPLETE business process: include every required
  validation / posting / approval step, take the correct conditional branch, and
  apply the correct record scope and filters.
- Do not drop a required step, leave a branch unhandled, or widen/narrow a filter
  beyond what the requirement specifies.

## L5 - Toolchain / Ecosystem Constraints

- Only reference objects, fields, methods, and events that actually exist and are
  accessible to the extension.
- Do not assume a record exposes a field or method it does not have, and do not
  call inaccessible or `Internal` members or non-existent events.

## How to use

1. Read the issue and the code under change; identify which layers the fix touches.
2. Apply the bullets for those layers as you write the change.
3. Re-check the change against each applicable layer before finishing.
