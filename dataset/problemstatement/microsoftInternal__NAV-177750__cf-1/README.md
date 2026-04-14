# Title: [Project] Assembly to Order and Create inventory pick — blank planning-line bin
## Repro Steps:
Locations silver - add yourselves as warehouse employee,
Activate Project Consumption Handling = Inventory Pick.
Post item journal with items 1920-s and 1968-s on location Silver, Bin S1.
Set Location Silver "Asm.-to-Order Shpt. Bin Code" to a valid bin (e.g. S1).

Create project for any customer (10000)
Add job task
Add job planning line
Budget, Item 1925-s, Location Silver, **leave Bin Code blank**, Qty 3, Qty to Assemble 3.
Assemble order created.

From project card, choose Create Inv Pick.
The pick flow must succeed by resolving the bin from the location's Asm.-to-Order Shpt. Bin Code when the planning line bin is blank.

Post the inventory pick.
Expected: Posted Assemble-to-Order Link is created.

## Description:
Variant of NAV-177750 where the job planning line has no explicit bin code. The system must resolve the assembly bin unconditionally from Location."Asm.-to-Order Shpt. Bin Code" rather than guarding on "Require Shipment".
