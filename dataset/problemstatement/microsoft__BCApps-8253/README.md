# (Bug 633226): [Subcontracting] Standard Task not propagated from Routing to Prod. Order Routing or Subcontracting Worksheet; prices not picked up

## Summary

The Subcontracting Worksheet flow was dropping `Standard Task Code` between the Prod. Order Routing Line and the Requisition Line, the field on the worksheet was read-only, and Subcontractor Prices keyed on a Standard Task were therefore never applied. This change:

- Propagates `Standard Task Code` from `Prod. Order Routing Line` to `Requisition Line` in both worksheet-population paths (Calculate Subcontracts… on the worksheet, and direct PO creation from a Prod. Order Routing line).
- Makes the `Standard Task Code` field editable on the Subcontracting Worksheet so users can override it.
- Causes the standard-task-bound subcontractor price to flow through to the Subcontracting Purchase Order's `Direct Unit Cost`.

The bug enumerated four symptoms (Routing → Prod. Order Routing, Prod. Order Routing → Worksheet, field not editable, prices not picked up). Routing → Prod. Order Routing was already handled by `Prod. Order Routing Line.CopyFromRoutingLine`; no change there. The remaining three are addressed below.

## Changes

### `SubcCalcSubcontractsExt.Codeunit.al`
Extended the existing `OnAfterTransferProdOrderRoutingLine` subscriber on report `Subc. Calculate Subcontracts` to also `Validate("Standard Task Code", ProdOrderRoutingLine."Standard Task Code")` on the new requisition line. Using `Validate` (not direct assignment) fires the field's OnValidate trigger in `Subc. RequisitionLine`, which calls `UpdateSubcontractorPrice` → `Subc. Price Management.GetSubcPriceForReqLine`. The price lookup already filters `Subcontractor Price` by `RequisitionLine."Standard Task Code"` exactly, so the standard-task-bound price is applied immediately.

### `SubcPurchaseOrderCreator.Codeunit.al`
Same fix in `InsertReqWkshLine`, which is the alternate worksheet-line builder used when a Subcontracting PO is created directly from a Prod. Order Routing Line (bypassing the worksheet UI).

### `SubcSubcontractingWorksheet.Page.al`
Removed `Editable = false` from the `Standard Task Code` field and added a tooltip clarifying that editing the value re-applies the matching subcontractor price. The field's OnValidate already triggers price re-lookup, so manual edits/clears on the worksheet immediately update `Direct Unit Cost`.

Fixes [AB#633226](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/633226)

