# Undo Shipment fails for a drop shipment with a blank bin code

## Description

**Undo Shipment** fails for an uninvoiced drop shipment when the posted sales shipment and linked purchase receipt have a blank **Bin Code** at a bin-mandatory location.

## Steps to reproduce

1. Create location `DOCKZILLA` with:
   - **Bin Mandatory** enabled;
   - **Default Bin Selection** set to **Fixed Bin**;
   - directed put-away and pick disabled;
   - warehouse receive, warehouse shipment, put-away, and pick requirements disabled.
2. Create a bin at `DOCKZILLA`, but do not configure a default bin for the test item.
3. Create a **Purchasing Code** with **Drop Shipment** enabled.
4. Create a sales order with one item line:
   - **Quantity** = `1`;
   - **Location Code** = `DOCKZILLA`;
   - the drop-shipment purchasing code.
5. Verify that **Bin Code** remains blank.
6. Create the linked purchase order and verify that **Location Code** is `DOCKZILLA` and **Bin Code** remains blank.
7. Post the purchase order as **Receive** only. Do not invoice the purchase receipt or linked sales shipment.
8. Open the posted sales shipment, select the item line, and run **Undo Shipment**.

## Expected behavior

Business Central creates the corrective shipment and receipt entries, restores the outstanding quantities on both orders, preserves the drop-shipment applications, and creates no warehouse-bin movement.

## Actual behavior

Undo Shipment fails with:

> The Bin does not exist. Identification fields and values: Location Code='DOCKZILLA', Code=''
