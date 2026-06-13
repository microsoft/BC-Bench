---
bc-version: [all]
domain: privacy
keywords: [page, card, list, api, listpart, permission-system, display, ui-dialog]
technologies: [al]
countries: [w1]
application-area: [all]
---

# Displaying fields on a page (or in a UI dialog) is not a privacy concern

## Description

Every page in Business Central — `Card`, `List`, `API`, `ListPart`, request pages — renders data to an authenticated user who has been granted permission to see it. The BC permission system, not the page definition, controls who sees what; once a user is permissioned to a table, displaying any field of that table is normal business functionality. The same logic extends to `Message`, `Notification` and `Confirm` dialogs: the signed-in user already has access to the data the dialog is showing them. Privacy review for pages and dialogs is therefore the wrong layer — the actionable findings live on the underlying data (table-field classification, telemetry message text, outbound HTTP consent), not on the UI.

## Best Practice

When asked "is it OK to show this email/name/employee code on this page?", the answer is yes — provided the user has permission to the underlying record. Drive privacy concerns to the data layer (classification, telemetry, external transfer) rather than the UI layer.

## Anti Pattern

Flagging an API page, list, card, or notification for surfacing customer-bearing fields (`E-Mail`, `Name`, `Phone No.`, audit fields, `User ID`). The permission system governs visibility; the page does not.
