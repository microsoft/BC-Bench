# Title: Reservation Worksheet creates a Reservation for Item that has 'Reserve' = Never
## Repro Steps:
1. Create new Item or go to item with no records.
2. On the item card, set the 'Reserve' = NEVER
3. Create Item Journal, Positive Adjustment for BLUE location and 10 qty.
4. Post this
5. Create Sales Order for Customer 50000 with the New item on the line with BLUE Location and 3 Quantity.
6. Go to the Reservation Worksheet.
7. Choose Process > Get Demand and set Demand Type = Sales, Item No. = Your Item.
8. Sales and service demand should not pull in here, but other demand types may still appear.

## Description:
Reserve = Never restriction applies only to Sales and Service demand, not to Assembly or Job Planning.
