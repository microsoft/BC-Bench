# [E-Document] Data Exchange v2 import handler (bridge pattern)

## Summary
- Add `IStructuredFormatReader` implementation for Data Exchange format (codeunit 6407)
- Bridge existing Data Exchange Definition infrastructure to v2 import pipeline staging tables
- Register as enum value 5 "Data Exchange" on `E-Doc. Read into Draft`
- Namespace-based definition matching (replaces v1 trial-and-error auto-detection)
- Run Data Handling Codeunit only (skip Pre-Mapping codeunit 6156 — vendor/GL resolution deferred to Prepare Draft)
- Map Intermediate Data Import records to `E-Document Purchase Header` / `E-Document Purchase Line` via field-ID bridge
- Process base64 attachments from Document Attachment intermediate records
- XPath supplement for Company Information fields not in intermediate data
- Integration events for partner extensibility

### New codeunit
| ID | Name | Purpose |
|----|------|---------|
| 6407 | E-Document Data Exch. Handler | IStructuredFormatReader for Data Exchange format |

### Key design decisions
- **No Commit()** — ReadIntoDraft runs inside pipeline try-function context
- **No EDocument.Modify()** — record passed by value; local variables used
- **Namespace matching** — matches XML root namespace against DataExchLineDef.Namespace instead of v1's trial-and-error (which requires Commit())
- **Data Handling only** — runs codeunit 1214 to populate Intermediate Data Import, skips Pre-Mapping (6156) since v2 Prepare Draft handles vendor/item resolution

## Test plan
- [x] Invoice ReadIntoDraft: header fields mapped (vendor name, invoice no, dates, amounts)
- [x] Invoice ReadIntoDraft: line fields mapped (description, quantity, unit price, line numbers)
- [x] Invoice returns "Purchase Invoice" process draft type
- [x] CreditNote returns "Purchase Credit Memo" process draft type
- [x] Total VAT computed correctly
- [x] Attachments decoded from base64 and stored
- [x] Currency code blank when matching LCY

[AB#630822](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/630822)
[AB#599123](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/599123)































