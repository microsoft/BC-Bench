# [master] [All-E]-[Repair Item][SaaS][Drop shipment reversal] Undo Shipment fails with blank Bin Code at bin-mandatory location

## Repro Steps

1. Create a location with Bin Mandatory enabled, Default Bin Selection set to Fixed Bin, directed put-away and pick disabled, and all warehouse receive/shipment/put-away/pick requirements disabled.
2. Create a bin, but do not configure a default bin for the item at that location.
3. Create a purchasing code with Drop Shipment enabled.
4. Create a sales order item line at the location with quantity 1 and the drop-shipment purchasing code. Verify that Bin Code remains blank.
5. Create the linked purchase order. Verify that its Location Code is populated and Bin Code remains blank.
6. Post the purchase order as Receive only. Do not invoice the purchase receipt or linked sales shipment.
7. Open the posted sales shipment, select the item line, and run Undo Shipment.

**Actual:**

```
The Bin does not exist. Identification fields and values: Location Code='DOCKZILLA', Code=''
```

**Expected:** Business Central creates corrective shipment and receipt entries, reverses the linked purchase receipt, restores sales-order and purchase-order quantities, keeps drop-shipment applications balanced, and creates no inappropriate warehouse-bin movement.

## Description

**Source:** [IcM 21000001869862](https://portal.microsofticm.com/imp/v5/incidents/details/21000001869862/summary)

**Problem:** Sales-side Undo Shipment fails for an uninvoiced drop shipment when the posted sales shipment and purchase receipt retain a blank Bin Code at a bin-mandatory location.

**Likely cause:** Codeunits 5815 and 5813 copy blank posted-document Bin Codes into corrective item-journal lines. Mandatory-bin validation then rejects the empty bin. This is a supported hypothesis; runtime root cause is not yet established.

**Affected version observed:** Base Application 28.3.52162.53835.

**Engineering notes:** Reproduce on extension-free 28.3 and current main. Capture the AL stack and posted-line Bin Codes. Validate whether corrective drop-shipment posting should preserve drop-shipment semantics or bypass physical bin handling. Do not substitute an arbitrary default bin without validating inventory-ledger and warehouse semantics.
