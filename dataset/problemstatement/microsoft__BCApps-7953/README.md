# Bug 623926: Add configurable default posting date for e-document purchases

## Why

When the Payables Agent (or manual processing) creates purchase invoices and credit memos from incoming e-documents, the posting date always defaults to the current work date — ignoring the document date present in the e-document. This forces users to manually correct the posting date to match the original invoice date, which is error-prone and inconvenient.

## Summary

- **Added** `E-Doc. Default Posting Date` enum with "Work Date" (default) and "Document Date" options
- **Added** corresponding field to the Purchases & Payables Setup table and page extensions, allowing users to configure the behavior
- **Added** `ApplyDefaultPostingDateFromSetup` procedure in `EDocPurchDocHelper` — called during both invoice and credit memo creation to set the posting date from the e-document's document date when the setting is "Document Date"
- **Added** 4 tests covering invoice and credit memo scenarios for both posting date options, plus a new PEPPOL test resource XML

[AB#623926](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/623926)






