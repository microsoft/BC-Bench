---
bc-version: [all]
domain: privacy
keywords: [data-classification, page-field, table-field, api-page, card-page, list-page]
technologies: [al]
countries: [w1]
application-area: [all]
---

# DataClassification is a table-field property, not a page-field property

## Description

`DataClassification` is defined on table fields. Pages — including `Card`, `List`, `API`, and `ListPart` — do not own a classification; they simply expose fields whose classification is inherited from the underlying table. A page-level `DataClassification` property does not exist, so neither a missing nor a "wrong" classification can be reported against a page. When the underlying table field is misclassified, the fix is on the table definition, not on every page that surfaces the field.

## Best Practice

When reviewing a page that exposes a field believed to be under-classified, follow the field back to its source table and inspect (or correct) the `DataClassification` there. A single corrected table field propagates to every page, report and API that uses it.

## Anti Pattern

Flagging a page (or trying to add a `DataClassification` property to a page field) because the page displays personal data. Pages display data that authenticated, permissioned users are already entitled to see; the classification belongs on the table field that stores the data, not on the UI that renders it.
