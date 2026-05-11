# Title: Posted Transfer Shipment - Undo Shipment function - valuation issue
## Repro Steps:
We encountered an error when using Undo Shipment function from Posted Transfer Shipment.
If, after posting the transfer shipment, a revaluation of the original item ledger entry that was used to apply the shipment is performed and then the transfer shipment is returned using the Undo Shipment function without running cost adjustment, then the item ledger entry created by this function is not correctly valued.

![Item Ledger Entries](./item-ledger-entries.png)

## Description:
Undo posted transfer shipment without running cost adjustment results in old cost being used.
