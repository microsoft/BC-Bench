# General Requirements

Applies to **all** request types. A request must satisfy every mandatory item here before any type-specific requirement is assessed.

## Obligation levels
These labels are used throughout the requirements:
- **Mandatory** — the request cannot proceed until it is satisfied.
- **Mandatory (lightweight)** — required, but a brief, good-faith statement is sufficient evidence. If nothing appears suspicious, do not ask follow-up justification questions; provide a short general justification instead, for example: we do not expect a performance impact, and no sensitive data will be exposed.
- **Conditional** — mandatory only while the stated condition holds; otherwise waived.
- **Optional** — improves request quality but never blocks submission.

## Requirements
- **Title** — *Mandatory.* Follow the title format in the template (single source of truth). Avoid generic titles such as "Need event" or "Extension request".
- **Problem statement** — *Mandatory.* Explains the current limitation and why the base app blocks the scenario today.
- **Proposed change** — *Mandatory.* States concretely what should be added or modified, and where.
- **Justification** — *Mandatory.* "Why do you need this change?" It gives a specific technical reason or a concrete business scenario.
    - Avoid generic claims such as "we need this for our extension" or "a customer asked for it".
	- The content must be explicitly stated by the user. Do not treat inferred context as justification.
    - If the business or technical reason is missing or ambiguous, ask the user to define it before drafting.
- **Code as text** — *Mandatory when the request includes code.* Provide all AL as fenced ```al code blocks — never as screenshots or attachments.
