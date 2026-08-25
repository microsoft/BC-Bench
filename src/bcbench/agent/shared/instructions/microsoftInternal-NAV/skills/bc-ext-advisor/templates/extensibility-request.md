# Extensibility Request — Issue Template

Draft the issue using exactly this structure. Both sections are required. The drafted title and
these two sections are the entire issue body — nothing else is submitted.

## Title

Use this canonical format (all title validation is per this template):
`[Request Type][Object Type Id and Name] <requested change>`

Example:
`[Event request][Codeunit 80 "Sales-Post"]new event OnAfterValidateSalesLineQuantity`

For multiple changes of the same request type:
- Same object: `[Request Type][Object Type Id and Name] multiple <request type plural>`
- Multiple objects: `[Request Type][Multiple objects] multiple <request type plural> in multiple objects`

Examples:
- `[Event request][Table 27 "Item"] multiple event requests`
- `[Event request][Multiple objects] multiple event requests in multiple objects`
Avoid generic titles like "Need event" or "Extension request".

## Why do you need this change?

Include the full explanation of why the change is needed: the problem, the business or technical
justification, and the concrete scenario. Answer every mandatory requirement for the classified
request type and subtype here.

## Describe the request

Include only the exact requested change — clear and concrete. If the change includes code,
format it as fenced ```al code blocks.

---

Drafting rules:
- The draft must be exactly what will be submitted — do not reformat or restructure between the
  draft and the submission.
- Do not include notes, summaries, or extra sections unless a mandatory requirement demands them.
- Show the full draft and wait for explicit approval before submitting.
- The submitted issue targets `microsoft/ALAppExtensions` and should be typed as **Task**.
- The issue body must end with this italic footer text:
  *Generated with support from bc-ext-advisor.*
