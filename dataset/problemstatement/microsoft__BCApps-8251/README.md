# Add VAT rate resolution and VAT amount difference for E-Document purchases

## Why

When importing e-documents for purchase processing, the system did not automatically resolve VAT Product Posting Groups from extracted VAT rates. Users had to manually identify and assign the correct VAT posting group for each line, which was error-prone and time-consuming. Additionally, rounding differences between the document's total VAT and the computed line-level VAT amounts were not reconciled, leading to posting discrepancies.

## Summary

- **Added** VAT Product Posting Group resolution during Prepare Draft — matches the extracted VAT rate against VAT Posting Setup entries (Normal VAT and Reverse Charge VAT only) for the vendor's VAT Bus. Posting Group
- **Added** `[BC] VAT Prod. Posting Group` and `[BC] VAT Rate Mismatch` fields on E-Document Purchase Line with OnValidate/OnLookup support
- **Added** VAT amount difference computation and application to purchase lines when finalizing drafts, respecting Allow VAT Difference and Max. VAT Difference Allowed settings
- **Added** "Resolve VAT Group Purch EDoc" and "Apply VAT Diff. For Purch EDoc" toggles on Purchases & Payables Setup
- **Improved** ADI handler to prefer the unambiguous `taxRate` field and properly disambiguate the `tax` field between percentage and monetary values
- **Added** comprehensive test codeunit `E-Doc Purch. VAT Tests` covering resolution, mismatch detection, OnValidate behavior, and VAT calculation type filtering
- **Updated** existing structured validation tests to reflect corrected VAT rate expectations

Fixes [AB#619564](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/619564)






