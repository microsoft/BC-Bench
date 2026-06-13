---
bc-version: [all]
domain: security
keywords: [validatetablerelation, tablerelation, field, validation, input]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Do not set ValidateTableRelation = false on user-editable fields

## Description

`TableRelation` on a field declares that the field's value must exist in another table; the platform validates the value on entry and on `Validate`. Setting `ValidateTableRelation = false` keeps the relation as metadata (used by lookups, by Edit-in-Excel, by APIs) but turns off the runtime check. On a system-controlled, non-editable field that is populated only by the platform or by a posting routine, that is acceptable. On a user-editable field, it is dangerous: users can type any value, and downstream code that assumes the relation holds will read a `Customer` record that does not exist, post to an account that was deleted, or join against missing rows.

## Best Practice

Leave `ValidateTableRelation` at its default (true) on any field a user can edit. If there is a legitimate reason to turn it off — typically because the relation is not on the primary key, or because the relation is computed — replace it with an `OnValidate` trigger that performs the equivalent check (`if FieldValue <> '' then VerifyExternalReferenceExists(FieldValue)`). Combine `ValidateTableRelation = false` with `Editable = false` for system-controlled fields, so the metadata is correct and the field is unreachable from the UI. See sample: `validatetablerelation-false-on-user-input.good.al`.

## Anti Pattern

`ValidateTableRelation = false` on a user-facing input field (a `Customer No.` typed by a sales user) with no alternative validation. Reviewers should flag the combination of `ValidateTableRelation = false` and any of: `Editable = true` (the default), an `OnValidate` trigger that does not perform the relation check, or a page that surfaces the field as input. See sample: `validatetablerelation-false-on-user-input.bad.al`.
