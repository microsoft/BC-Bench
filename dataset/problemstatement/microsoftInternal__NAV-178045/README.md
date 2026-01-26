# Title: Error when trying to post Consumption that is reserved to multiple Lot Tracked ILEs: You have insufficient quantity of Item xyz on Inventory
## Repro Steps:
1. "Mfg. Setup" had BLUE set Comp. at Location.
2. Create Purchased Item TONY CONSUMPTION LOT, with RESERVE ALWAYS, and LOT Tracked, Manual Flushed.
3. Create Produced Item TONY PARENT, that consumes previous item in a new BOM.
4. Create 3 Item Journal lines for item TONY CONSUMPTION LOT, positive adjustment for 5, 10, 20 qty all with same LOT Number "TONYLOT01" at BLUE Location (Should be 35 total qty)....and POST it.
5. Created Released Prod. Order for 35 qty of TONY PARENT, at BLUE Location
6. Refresh Production Order
7. On the Prod. Order, you can go into the Line > Components and can see 35 reserved to existing 3 layers of stock (from step 4)
8. On the Prod. Order, go to LIne > Production Journal, and on the Consumption line, go into the Item Tracking and select the 'Lot' = "TONYLOT01" for 35 Quantity.
9. You can 0 out the Output Quantity for Output Line on Prod. Journal.
10. Now try to post the Consumption.

**EXPECTED RESULT:** 35 quantity would be consumed during posting.
**ACTUAL RESULT:** Error: **"You have insufficient quantity of Item xxx on Inventory."**

However, if I would break it down and consume the consumption line 3 different times, the first for 5 qty with TONYLOT01, then 10 qty with TONYLOT01, then 20 qty with TONYLOT01, you can post all 3 consumption postings.

## Description:
Derived from Support Case Review
