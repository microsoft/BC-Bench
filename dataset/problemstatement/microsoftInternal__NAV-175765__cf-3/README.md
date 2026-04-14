# Title: Posted Transfer Shipment - Undo Shipment function - valuation issue
## Repro Steps:
We encountered an error when using Undo Shipment function from Posted Transfer Shipment.
If, after posting the transfer shipment, a revaluation of the original item ledger entry that was used to apply the shipment is performed and then the transfer shipment is returned using the Undo Shipment function, then the item ledger entry should be valued at the revalued cost only if revaluation was applied before undo.

![Item Ledger Entries](./item-ledger-entries.png)

## Description:
Cost adjustment after undo should only apply revalued cost when revaluation exists for the original entry.
