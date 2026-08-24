# Event Request Requirements

Applies to `event-request`, in addition to the general requirements.

## Requirements
- **Exact location** — *Mandatory.* Identify the object (type, ID, and name) and the procedure or trigger, plus the precise insertion point relative to the surrounding statements.
- **Event signature** — *Mandatory.* Provide the proposed event name and full parameter list, including whether parameters pass by value or by reference.
- **Proposed code** — *Mandatory.* Provide the event declaration plus 5–10 lines of surrounding context.
- **Use-case example** — *Optional.* Describe how a subscriber will consume the event; a sample subscriber helps.
- **Meaningful justification** — *Conditional.* Not required when merely adding a parameter to an existing event, unless security, sensitive data, or performance is affected.
