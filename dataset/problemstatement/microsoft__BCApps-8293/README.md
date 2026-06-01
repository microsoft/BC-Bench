# Bug 634953: Fix factbox drilldowns for finished production orders

## Summary
- **Bug**: Subcontracting factbox drilldowns in Purchase Order and Transfer Order break after the linked production order is finished.
- **Root cause**: \Subc. ProdO. Factbox Mgmt.\ (CU 99001559) hardcodes \SetRange(Status, ::Released)\ in all 5 procedures, so no data is returned once status moves to Finished.
- **Fix**: Replace \SetRange(Status, ::Released)\ with \SetFilter(Status, '>=%1', ::Released)\ across all filter procedures so that both Released and Finished production orders are found. \ShowProductionOrder\ now opens the correct page (\Released Production Order\ or \Finished Production Order\) based on the resolved status.

## Changes
- \SubcProdOFactboxMgmt.Codeunit.al\ — Fixed all 5 affected procedures
- \SubcSubcontractingTest.Codeunit.al\ — Added \ProdOFactboxMgmtShowsDataAfterProdOrderFinished\ test ([SCENARIO 634953])

## Test
Added \ProdOFactboxMgmtShowsDataAfterProdOrderFinished\ in codeunit 139989 — verifies that \CalcNoOfProductionOrderRoutings\ and \CalcNoOfProductionOrderComponents\ return positive counts after the production order is finished.

Fixes [AB#634953](https://dynamicssmb2.visualstudio.com/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/_workitems/edit/634953)

:robot: Generated with GitHub Copilot



