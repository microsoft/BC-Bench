# Undoing a drop shipment fails when the location requires bins

## Reproduction steps

1. Create location `DOCKZILLA` with:
   - **Bin Mandatory** enabled;
   - **Default Bin Selection** set to **Fixed Bin**;
   - directed put-away and pick disabled;
   - warehouse receive, warehouse shipment, put-away, and pick requirements disabled.
2. Create a bin at `DOCKZILLA`, but do not assign a default bin for the test item.
3. Create a **Purchasing Code** with **Drop Shipment** enabled.
4. Create a sales order with one item line:
   - **Quantity** = `1`;
   - **Location Code** = `DOCKZILLA`;
   - the drop-shipment purchasing code.
5. Verify that **Bin Code** remains blank.
6. Create the linked purchase order for the drop-shipment sales line.
7. Verify that its **Location Code** is `DOCKZILLA` and **Bin Code** is blank.
8. Post the purchase order as **Receive** only. Do not invoice the purchase receipt or the linked sales shipment.
9. Open the resulting **Posted Sales Shipment**.
10. Select its item line, choose **Undo Shipment**, and confirm the action.

## Expected behavior

Business Central:

- creates corrective sales-shipment and purchase-receipt lines;
- restores the outstanding quantities on both orders;
- preserves drop-shipment semantics on the corrective item entries;
- creates no warehouse-bin movement.

## Actual behavior

Undo Shipment fails with:

> The Bin does not exist. Identification fields and values: Location Code='DOCKZILLA', Code=''
