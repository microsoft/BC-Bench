---
bc-version: [all]
domain: privacy
keywords: [error, strsubstno, direct-substitution, telemetry, classification, label]
technologies: [al]
countries: [w1]
application-area: [all]
---

# `Error()` with direct substitution parameters is always safe for telemetry

## Description

When `Error()` is called with a format string and direct substitution parameters (`%1`, `%2`, …), the BC platform intercepts the call, inspects each parameter individually, and applies the `DataClassification` of the source field — stripping or masking sensitive data before writing the message to telemetry. This is true regardless of whether a parameter is a record field reference, a local variable, a function return value, or any other expression. Patterns such as `Error('Invalid email: %1', Customer."E-Mail")` are therefore safe even when the parameter is PII: the platform sees `Customer."E-Mail"` as a `CustomerContent` field reference and handles it correctly.

## Best Practice

Pass values to `Error()` as direct substitution parameters — either inline or via a `Label` with `Comment = '%1 = …'` placeholders. Let the platform do the per-parameter classification. This works equally well for record fields, local text variables, and document IDs.

See sample: `error-direct-substitution-safe-for-telemetry.good.al`.

## Anti Pattern

Treating any `Error()` call that mentions PII as a leak. A review skill that flags `Error('Invalid email: %1', EmailAddress)` is wrong; the platform handles that pattern correctly. The only `Error()` shape that genuinely leaks PII to telemetry is the pre-built `StrSubstNo` form covered in `avoid-strsubstno-prebuild-before-error.md`.
