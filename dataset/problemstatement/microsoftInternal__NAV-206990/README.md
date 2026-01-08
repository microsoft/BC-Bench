Title: [ALL-E] [Manufacturing BB2] - Cannot finish cost adjustment after reopen/close production order.
Repro Steps:
Create production order for item 1000, post some output, finish. The production order in table 5896 Inventory Adjmt. Entry (Order) is marked as finished. Run Adjust Cost - Item Entries. Now the item 1000 is marked with "Cost is Adjusted". The record 5896 is also marked as adjusted. Reopen production order. Both "Finished" and "Cost is Adjusted" fields on the record 5896 are reset. The item remains adjusted. Finish the production order. Run Adjust Cost - Item Entries. The record 5896 is not updated, because the cost adjustment skips adjusted items and therefore skips records 5896 that belong to these items. Could be that we need to set "Cost is Adjusted" = false for the item as well.
Description:

