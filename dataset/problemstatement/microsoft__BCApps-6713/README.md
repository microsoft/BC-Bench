# [master][all-e]"The changes to the subscription line record cannot be saved..." error when you change a newly create line in a customer subscription contract

## Repro Steps

1. Open the Subscription Contract Setup and add any
   existing No Series to fields „Customer Subscription Contract Nos“ and „Subscription
   Nos“
2. Go to Items and create a new Non-Inventory item.
   Leave all fields as suggested, just change field „Subscription Option“ to „Subscrpition
   Item“
3. Go to Customer Subscription Contracts and create
   a new one for customer 10000
4. In the lines add the subscription item created
   in step 2
5. change
   the Subscription  Description to
   "TEST"
6. change
   the Subscription Line Description to "TEST"
7. Enter a "Calcualtion Base Amount"

Actual result:

"The
changes to the subscription line record cannot be saved..." error when you
change a newly create line in a customer subscription contract

Expected
result:

No error message should appear

More
Information:

Same issue
happens with Vendor Subscription Contract – please also correct the purchase
side.
