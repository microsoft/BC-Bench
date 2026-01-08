Title: [ALL-E] [S11] Missing Non-Inv line in the production order statistics
Repro Steps:
make sure there is non-inv item in the bom and FG has standard cost. For example: Item with cost 100 and qty 1 Non-inv with cost 1 and qty 10. Select this bom in item FG, make sure the costign method is Standard cost. Calculate standard cost (should be 110) Create new released production order for that item qith qty 1. Refresh. Navigate to Components and change qty for both lines: Invneotry = 2 Non-inventory = 20. Post consumtion of both inventory and non-inventory items. Invenotry qty = 3 Non-inventory qty = 30 Explore statistics. Material cost includes both Inventory and non-Inventory items. Expected - separate line for Non-inventory material cost. (i remember we discussed it this way, but later we decided to split Non-inv in the Cost Share report, so makes sense to align.)
Description:

