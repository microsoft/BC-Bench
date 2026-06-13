---
bc-version: [all]
domain: privacy
keywords: [strsubstno, error, telemetry, pii, prebuild, text-variable]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Do not pre-build an error string with `StrSubstNo` before calling `Error()`

## Description

`StrSubstNo` returns a plain `Text` value with the substitutions already performed. When that result is then passed to `Error()`, the platform sees a single plain-text parameter with no field references left to inspect, so it cannot apply `DataClassification` to anything inside it. Whatever PII the `StrSubstNo` call interpolated — customer name, e-mail, address, error text — is logged verbatim to telemetry. This is the canonical way to accidentally leak customer data through error telemetry, and it is the only `Error()` shape that needs to be flagged.

## Best Practice

Call `Error()` directly with the format string and the substitution parameters. The platform classifies each parameter individually and handles telemetry correctly even when the parameters are PII fields (see `error-direct-substitution-safe-for-telemetry.md`). If the message text needs to be a `Label`, pass the `Label` and the parameters to `Error()` — do not pre-render via `StrSubstNo`.

See sample: `avoid-strsubstno-prebuild-before-error.good.al`.

## Anti Pattern

Assigning `StrSubstNo('Customer %1 (%2) ...', Customer.Name, Customer."E-Mail")` to a `Text` variable and then calling `Error(ErrorMsg)`. The platform has nothing to classify by the time `Error` runs — the PII is baked into the string and goes straight to telemetry. Detection signal for a reviewer: any `Text` variable assigned from `StrSubstNo` and later passed as the *only* parameter to `Error()`.

See sample: `avoid-strsubstno-prebuild-before-error.bad.al`.
