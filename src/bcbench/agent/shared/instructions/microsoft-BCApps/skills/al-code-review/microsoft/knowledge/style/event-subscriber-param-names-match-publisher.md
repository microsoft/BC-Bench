---
bc-version: [all]
domain: style
keywords: [event-subscriber, parameter-name, publisher, signature, eventsubscriber]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Event subscriber parameter names must match the publisher signature

## Description

In AL, an `[EventSubscriber]` procedure is bound to its publisher by event name and parameter list. The parameter names on the subscriber are not a style choice — they must match the names the publisher declared. The compiler validates the match at build time and emits an error if the subscriber renames a parameter. This means a reviewer cannot apply a generic "use better names" pass to subscriber parameters: `Sender`, `Rec`, `xRec`, `RunTrigger`, the table-and-field-specific parameter names a publisher emits — all are dictated by the publisher and must be reproduced verbatim.

## Best Practice

Copy the publisher signature exactly when declaring the subscriber. When in doubt, navigate to the publisher (`OnAfterValidateEvent`, `OnBeforePostSalesDoc`, etc.) and copy its parameter list. Style rules that apply to other locals — descriptive names, no spaces — do not apply to subscriber parameters.

## Anti Pattern

Renaming a publisher parameter to look prettier in the subscriber. The build breaks immediately. More insidiously, a parameter name that happens to match by coincidence in one event publisher but not in a similar one will compile in some versions of BC and fail in others when the publisher signature evolves.
