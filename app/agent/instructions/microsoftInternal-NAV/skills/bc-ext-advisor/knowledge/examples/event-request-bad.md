# Event Request — Bad Example

An example of a request that should be sent back for more information.

## Why do you need this change?

> "We need an event here for our extension."

## Describe the request

> "Please add an event in the sales posting codeunit so we can do our stuff."

Why this is bad:
- **Generic justification** — "for our extension" / "do our stuff" is not a concrete business or technical scenario.
- **No exact location** — "the sales posting codeunit" does not identify the procedure or the insertion point.
- **No code and no signature** — there is no proposed event name, parameters, or surrounding context.
- **Unclear whether an existing event already covers the need** — no alternatives were considered.

The correct response is to ask, in a single focused pass, for: the exact procedure/location, the event name and parameters, and the specific scenario — and to check whether a nearby existing event already satisfies the need before drafting anything.
