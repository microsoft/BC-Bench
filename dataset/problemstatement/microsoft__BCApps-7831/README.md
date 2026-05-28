# Bug 620556: [Subcontracting] Align Subcontracting app with changes to the "Description 2" on various tables

## Summary

- **SubcPurchaseOrderCreator**: copy `Description 2` from `ProdOrderComponent` (not `Item`) to `PurchaseLine`; copy from `ProdOrderRoutingLine` (not blank) to `RequisitionLine`
- **SubcTempDataInitializer**: propagate `Description 2` from `RoutingLine` → temp `ProdOrderRoutingLine` and from `ProductionBOMLine` → temp `ProdOrderComponent`
- **SubcCreateProdOrdOpt**: include `Description 2` in `SetLoadFields`; propagate it to `PurchaseLine`, `ProductionBOMHeader`, `RoutingHeader`, `ProdOrderComponent`, and `ProdOrderRoutingLine` when committing wizard data
- **Pages**: surface `Description 2` (hidden) on `SubcProdOrderComponents`, `SubcPurchProvisionWizard`, and all four wizard list part pages

## Root cause

Bug 617366 added the `Description 2` field to manufacturing tables in the base app. The Subcontracting app was not updated to propagate that field through its wizard pipeline or purchase order creation flow, causing the field to be lost or blanked.

Fixes [AB#620556](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/620556)

🤖 Generated with [Claude Code](https://claude.com/claude-code)




