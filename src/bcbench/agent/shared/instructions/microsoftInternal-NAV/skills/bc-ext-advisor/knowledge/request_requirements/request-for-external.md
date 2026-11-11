# Request-for-External Requirements

Applies to `request-for-external`, in addition to the general requirements. Covers widening a member's visibility (local/internal → public/global) or removing an `OnPrem` scope restriction.

## Safety classification
Classify the target member before deciding how much justification to require:
- **Safe** — simple validation, read-only access, or formatting/calculation helpers with no side effects. Accept with minimal justification, including "to avoid duplicating base logic".
- **Risky** — accesses passwords, secrets, or tokens; performs authentication or encryption; bypasses permission checks; or could enable cross-prompt injection. Require full justification.

## Requirements
- **Target member** — *Mandatory.* Identify the object, member, and the exact visibility change. May be satisfied by explicit code or by the advisor locating the member.
- **Usage scenario** — *Mandatory (relaxed for safe members).* Describe how and from where the member will be consumed. When the member is safe and the goal is to avoid code duplication, "to avoid duplicating base logic" is sufficient.
