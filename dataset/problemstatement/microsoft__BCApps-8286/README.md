# (Bug 636078): [Subcontracting] Worksheet pricing passes total base qty instead of qty-per-UoM to ConvertPriceToUOM — wrong Direct Unit Cost

## Summary

Fixes the Subcontracting Worksheet **Direct Unit Cost** when the production order UoM differs from the subcontractor price-list UoM.

`Subc. Price Management.GetSubcPriceForReqLine` passed `RequisitionLine.GetQuantityBase()` (total base quantity of the order) as the per-UoM conversion factor to `ConvertPriceToUOM`. Because `ConvertPriceToUOM` computes `DirectCost := PriceListCost / PriceListQtyPerUOM * ProdQtyPerUoM`, the result was multiplied by the order quantity instead of the UoM conversion factor. The Carry-Out Action Message-created Purchase Order then inherited the inflated cost.

Comparison of the three call sites (only the worksheet path was wrong):

| Path | 2nd param | Correct? |
|------|-----------|----------|
| Routing (`SetRoutingPriceListCost`) | `ProdQtyPerUom` | Yes |
| **Worksheet (`GetSubcPriceForReqLine`)** | **`RequisitionLine.GetQuantityBase()`** | **No (fixed here)** |
| Purchase Order (`GetSubcPriceForPurchLine`) | `PurchaseLine.GetQuantityPerUOM()` | Yes |

### Fix

Pass `RequisitionLine.GetQuantityForUOM()` instead, matching the routing and purchase paths.

### Test

Added `WorksheetDirectUnitCostUsesQtyPerUoMNotBaseQtyForUoMConversion` in `SubcSubcontractingTest`:

- Item with PCS base UoM + SET alternative UoM (10 PCS per SET), vendor and work center with that vendor as subcontractor, subcontractor price of 1000 / PCS.
- Stages a Requisition Line for 3 SET (= 30 PCS base) and asserts `Direct Unit Cost = 10000` (price * Qty-per-UoM), not 30000 (pre-fix behavior).
- Also asserts the same-UoM (PCS) path still returns 1000 - guards against regression.

### Work Item

[AB#636078](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/636078)
