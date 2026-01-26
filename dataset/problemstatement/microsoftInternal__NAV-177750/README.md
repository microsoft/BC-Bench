# Title: [Project] Assembly to Order and Create inventory pick
## Repro Steps:
Locations silver - add yourselves as warehouse employee,
Activate Project Consumption Handling = Inventory Pick.
Post item journal with items 1920-s and 1968-s on location Silver, Bin S1.

Create project for any customer (10000)
Add job task
Add job planning line
Budget, Item 1925-s, Location Silver, Bin S7 (not empty), Qty 3, Qty to Assemble 3.
Assemble order created.

From project card. choose Create Inv Pick.
Result - There is nothing to create.

Navigate to inv picks, create one manually. Use Get Source Document to find project. Try to get it.
Result - there is nothing to create.

Navigate to Location Silver and activate "Always Create Pick lines"

Try to create inventory pick from Job:

The Bin does not exist. Identification fields and values: Location Code='SILVER',Code='

AL call stack:
"Create Inventory Pick/Movement"(CodeUnit 7322).GetBin line 5 - Base Application by Microsoft
"Create Inventory Pick/Movement"(CodeUnit 7322).GetSpecEquipmentCode line 6 - Base Application by Microsoft
"Create Inventory Pick/Movement"(CodeUnit 7322).SetLineData line 22 - Base Application by Microsoft
"Create Inventory Pick/Movement"(CodeUnit 7322).MakeWarehouseActivityLine line 13 - Base Application by Microsoft
"Create Inventory Pick/Movement"(CodeUnit 7322).CreatePickOrMoveLine line 176 - Base Application by Microsoft
"Create Inventory Pick/Movement"(CodeUnit 7322).CreatePickOrMoveFromJobPlanning line 48 - Base Application by Microsoft
"Create Inventory Pick/Movement"(CodeUnit 7322).AutoCreatePickOrMove line 30 - Base Application by Microsoft
"Create Invt Put-away/Pick/Mvmt"(Report 7323)."Warehouse Request - OnAfterGetRecord"(Trigger) line 49 - Base Application by Microsoft

Similar steps for Sales Order (you need to activate Require Pick and add some bin content for item 1925-s - regression) works.

## Description:
