# Title: Reservation Worksheet creates a Reservation for Item that has 'Reserve' = Never
## Repro Steps:
1. Create new Item or go to item with no records.
2. On the item card, set the 'Reserve' = NEVER
3. Create Item Journal, Positive Adjustment for BLUE location and 10 qty.
4. Post this
5. Create Sales Order for Customer 50000 with the New item on the line with BLUE Location and 3 Quantity.
    NOTE, if you were to try manually reserving this, you will receive an error because the item has 'Reserve' = Never.
6. Go to the Reservation Worksheet.
7. Choose Process > Get Demand and set
    Demand Type = Sales
    Item No. = Your Item we are working with here.
8. Click OK and this is really where I want to point out the Results...
    **EXPECTED RESULTS:** The Item demand should not pull in here.
    **ACTUAL RESULTS:** This pulls in the Demand line for the 3 qty.
9. So now with the Actual Results, you then Choose Allocate > Allocate which sets 'Accept'=TRUE and 'Qty. to Reserve'=3
10. Choose Reserve > Make Reservation
    This now makes a Reservation for the Sales Line to the QOH.

## Description:
Derived from Support 'Case Review'
I'm not sure what exactly the design here is. Is this an oversight/code defect? I guess I would think if we had 'Reserve' = NEVER, that there would be validation in the Reservation Worksheet to not pull any items with that setting. We can't make a reservation from the Sales Order, but we are allowed to make one from the Reservation Worksheet? Is that correct?

But if this is really by design, which I think we are going to get some pushback from Partners/Customers if it is, but if that is the case then we should really have this documented in the following links:
[How to Reserve Items - Business Central | Microsoft Learn](https://learn.microsoft.com/en-us/dynamics365/business-central/inventory-how-to-reserve-items)
[Suggest the next step for sales and production orders | Microsoft Learn](https://learn.microsoft.com/en-us/previous-versions/dynamics365/release-plan/2023wave2/smb/dynamics365-business-central/suggest-next-step-sales-production-orders)
