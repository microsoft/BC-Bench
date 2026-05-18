# Port PEPPOL price-incl-VAT line amount fix to PEPPOL app

## Summary
Mirrors BaseApp commit 7999d10 (ADO PR 244837 / work item [AB#630795](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/630795)) into the standalone PEPPOL app. PEPPOL BIS 3.0 requires line amounts and discount amounts to be VAT-exclusive; the BaseApp `PEPPOL Management` codeunit was fixed but the equivalent code in `PEPPOL30 Impl.` was never updated, so e-invoices generated through the PEPPOL app still failed validation when `Prices Including VAT` was used on a sales document.

- `PEPPOL30Impl.GetLineGeneralInfo`: divide `Line Amount` by `(1 + VAT%/100)` when `Prices Including VAT` is true
- `PEPPOL30Impl.GetLineAllowanceChargeInfo`: same VAT adjustment for `Line Discount Amount`
- `PEPPOL30ManagementTests.VerifyGetLineGeneralInfo`: updated to apply the same adjustment in assertions
- New test `LineAmountsConsistentWhenPricesInclVATNoDiscount` asserts `LineExtensionAmount = PriceAmount * Quantity` per PEPPOL BIS 3.0





