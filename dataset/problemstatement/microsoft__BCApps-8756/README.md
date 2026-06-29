# Bug 640113: Vendor-Supplied components visible in Planning Worksheet after refresh

## Summary
- **Bug**: Lines with Subcontracting Type = Vendor Supplied are missing in Planning Worksheet when refreshing from Production BOM
- **Root cause**: The OnTransferBOMOnBeforeUpdatePlanningComp event subscriber was setting IsHandled := true for Vendor-Supplied components, completely blocking them from being created as Planning Components during the Refresh Planning Line operation.

## Fix
Removed the IsHandled := true from IgnorePurchaseComponentsFromSubcontracting_OnTransferBOMOnBeforeUpdatePlanningComp. Vendor-Supplied components are now transferred as planning components (so they appear in the Planning Worksheet component list and consumption can be registered). The exclusion from planning demand calculations remains correctly handled by ProdOrderComponent_OnAfterFilterLinesWithItemToPlan.

## Test
Added VendorSuppliedComponentVisibleInPlanningWorksheetAfterRefresh [SCENARIO 640113] verifying:
1. The Vendor-Supplied component exists in Planning Components after refresh
2. The Component Supply Method is correctly transferred
3. The component is relocated to the subcontractor location

Fixes [AB#640113](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/640113)


