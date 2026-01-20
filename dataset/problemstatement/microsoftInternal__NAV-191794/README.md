# Title: [Project Order replan] Create Purchase action also needed in the Project Planning Lines - follow up
## Repro Steps:
User feedback/telemetry

Project with many tasks and planning lines.

If user runs Create PO it will include items from all phases (tasks). As we can see in telemetry, they often create PO from project planning lines.

Expected:

Add Create Purchase Order action to the:

1.  Job Planning Lines (1007, List)
2.  Job Planning Lines Part (1015, ListPart)

Ensure filtering by task (in addition to project)

Create project with 2 tasks.

Task1
Task2

For task1 add line of type Budget, Item 1896-S, qty 100. (any item). all other fields are default (empty location, default dates)

For task2 add line of type Budget, Item 1896-S, qty 200. (any item). all other fields are default (empty location, default dates)

In task1, run Create Purchase Order. It suggests creating purchase order for item 1896-S, Qty ~100 (or 96, depending on stock level). Choose Cancel.

In task2, run Create Purchase Order. It suggests creating purchase order for item 1896-S, Qty ~200. Looks reasonable. Choose Ok. 

PO create, explore "Project No", "Project Task" fields to confirm that they are populated as expected (task2).

Return to project created earlier.

In task2, run Create Purchase Order. It suggests creating purchase order for item 1896-S, Qty ~100. **This is wrong.** As we already have PO that covers 100% of demand. Choose Cancel.

In task1, run Create Purchase Order. It says that there are enough inventory. **This is wrong**, po is linked to Task2 and once PO posted qty will be consumed for Task2.

## Description:

