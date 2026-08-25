# Enum Request Requirements

Applies to `enum-request`, in addition to the general requirements.

## Requirements
- **Requested enum change** — *Mandatory.* State whether the request creates a new enum, makes an existing enum extensible so customizations can add values, or replaces `Option` usage with an enum.
- **Target enum definition** — *Conditional.* If the request creates a new enum, provide the enum name and every value with its caption and ordinal. If the request uses an existing enum, identify that enum by name and ID.
- **New enum values** — *Conditional.* If the request adds values, list each new value with its caption and proposed ordinal.
- **Extensibility** — *Mandatory.* Confirm the relevant enum will be declared `Extensible = true` or, for an existing enum, is already declared `Extensible = true`. If it is not, state that it must be made extensible first before custom values can be added.
- **Usage scope** — *Mandatory.* Identify the tables, fields, pages, reports, procedures, parameters, or return values that will use the enum.
- **Option mapping** — *Conditional.* If the request replaces `Option` usage, list the current `OptionMembers` or logical option values and show how each maps to the enum values.
- **Compatibility check** — *Mandatory.* Confirm the change will not break existing behavior: whether base `case`/`if` logic handles unknown values gracefully, whether proposed ordinals could collide with other extensions, and whether data migration is required.
