Title: [ALL-E] [S9] Reverse consumption of non-inventory items - reversed entry has no cost
Repro Steps:
create item of type Non-Inventory, specify unit cost = 1. create released production order for any item (SP-SCM1009 or 1000 for dev environemnt). Qty 1 (any). Refresh. Navigate to Components, delete all lines, add new one with Non-Invetnory item, qty 10. Navigate to production journal and post consumption. Navigate to item ledger entries, find entry and choose Reverse transaction. Notice that Non-Invt Cost is empty for reversal entry. Expected - same as in original operation.
Description:

