# Fix E-Doc V1 PEPPOL import: Sub Total uses LineExtensionAmount from XML

## Summary

- **`EDocImport.Codeunit.al:843`** — `V1_CopyFromPurchaseLine` was setting `"Sub Total"` as `Direct Unit Cost * Quantity` instead of using `PurchaseLine.Amount` which holds the `LineExtensionAmount` parsed directly from the PEPPOL XML.
- **`EDocReceiveTest.Codeunit.al`** — Added regression test `ReceivePeppolInvoice_LineSubTotalFromXml` that verifies `"Sub Total"` = 11.20 for a line with Qty=1.65, Price=6.79, LineExtensionAmount=11.20.
- **`PEPPOL_LineRounding.xml`** — Minimal PEPPOL BIS 3.0 test invoice with rounding-sensitive quantities.

## Root cause

In the V1 import path, `EDocImportPEPPOLBIS30` reads `LineExtensionAmount` (the vendor-rounded line total) into `PurchaseLine.Amount`. But `V1_CopyFromPurchaseLine` ignored it and recalculated:

```al
// Before (bug):
EDocumentPurchaseLine."Sub Total" := PurchaseLine."Direct Unit Cost" * PurchaseLine.Quantity;
// 6.79 * 1.65 = 11.2035 — wrong, shows unrounded value on E-Document Purchase Draft page

// After (fix):
EDocumentPurchaseLine."Sub Total" := PurchaseLine.Amount;
// 11.20 — correct, preserves vendor-rounded value from XML
```

`PurchaseLine.Amount` is set from the XML via `Evaluate(PurchaseLine.Amount, Value, 9)` at `EDocImportPEPPOLBIS30:503` and is preserved through `MapEDocument` (which copies all fields and only transforms Text/Code types, not Decimal).

## Test plan
- [ ] `ReceivePeppolInvoice_LineSubTotalFromXml` passes: asserts `EDocumentPurchaseLine."Sub Total"` = 11.20

Fixes bug [AB#613698](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/613698)




