---
bc-version: [all]
domain: privacy
keywords: [getlasterrortext, error, strsubstno, telemetry, customer-data, attachment]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Treat `GetLastErrorText()` as potential customer content

## Description

`GetLastErrorText()` returns the text of the last error that occurred in the context where it is called. That text routinely contains customer content — field values that triggered the validation, record keys, customer names, file names from upload failures, and similar fragments lifted from the failing operation. Re-emitting it through `StrSubstNo` into `Error()` bakes that customer data into a single plain-text parameter that the platform can no longer classify, so it is logged verbatim to telemetry (the same problem as any other `StrSubstNo`-pre-built error — see `avoid-strsubstno-prebuild-before-error.md`).

## Best Practice

When the goal is to surface a recoverable failure to the user, raise a generic message that does not embed `GetLastErrorText()` content, and log technical detail separately via `Session.LogMessage` with the correct `DataClassification`. If you must propagate the inner error verbatim, re-raise it as a direct parameter of `Error()` (e.g., `Error('%1', GetLastErrorText())`) rather than concatenating with `StrSubstNo` so the platform can apply its own handling.

See sample: `getlasterrortext-customer-content-in-errors.good.al`.

## Anti Pattern

`ErrorMsg := StrSubstNo('Attachment failed: %1', GetLastErrorText(true)); Error(ErrorMsg);` — the inner error text may carry filenames or record values, and `StrSubstNo` strips the platform's ability to filter them before they hit telemetry.

See sample: `getlasterrortext-customer-content-in-errors.bad.al`.
