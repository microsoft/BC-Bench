Title: If a component's Item UOM has a 'Quantity Rounding Precision' of 1, & a Finished Good consumes partial quantity, the Prod. Order created from the Planning of a Sales Order pulls in the Component with a 'Qty. Per' and 'Exp. Qty.' of 0.
Repro Steps:
1. Use existing Item with no activity, or create new item. This will be the COMPONENT Item. Will use PCS as UOM.
2. For the Component Item, go into Related > Item UOM > and set 'Quantity Rounding Precision' = 1 on the bottom.
3. Component Item should have
  Replenishment System = PURCHASE
  Rounding Precision = .01
  Reorder Policy = Lot-for-Lot
  Include Inventory = TRUE
4. Then have another Item, I'll call it FG Item which is:
  Replenishment System = PRODUNCTION ORDER
  Rounding Precision = 1
  Reorder Policy = ORDER
  Production BOM => Create new Certified Production BOM that consumes COMPONENT Item with 'Quantity Per' = .09
5. Now create Sales Order for any Customer for FG Item for 1 Quantity at BLUE (or MAIN) location.
6. On the Sales Order go to Actions > Plan > Planning > Create Prod. Order and choose 'Released' and 'Item Order'.
7. Then choose Order Tracking and then 'Show' which will take you to the Released Prod. Order.
8. We will see prod. Order for FG Item with 1 qty. Go to Line > Components

**EXPECTED RESULTS** = 'Quantity Per' and 'Expected Quantity' = .09
**ACTUAL RESULTS** = 'Quantity Per' and 'Expected Quantity' = 0

If you were then to delete the Released Production Order, and go to the Planning Worksheet and run the Calc. Regenerative Plan for the 2 items, you would receive an error:
"The value in the Qty. Rounding Precision field on the Item Unit of Measure page is causing the rounding precision for the Expected Quantity field to be incorrect."

Description:
2If a component's Item UOM has a 'Quantity Rounding Precision' set to 1, and a Finished Good consumes partial quantity, the Production Order created from the Planning section of a Sales Order pulls in the Component but with a 'Quantity Per' and 'Expected Quantity' of 0. If we are producing 1 FG Item and the 'Quantity Per' is set to consume .1 component, we would expect 'Quantity Per' and 'Expected Quantity' both = .1. There is no error message.

But if you run the Planning Worksheet's 'Calc. Regenerative Plan', then you will get an error message about the 'Quantity Rounding Precision'.

I don't believe the 'Quantity Rounding Precision' in the Item UOM should have any influence on this process. I always thought this field was only for scenario with Picking and when Base UOM is larger than the smallest UOM, and picking in smallest UOM. There is a lot of confusion about this 'Quantity Rounding Precision' field within the Item UOM actually.
