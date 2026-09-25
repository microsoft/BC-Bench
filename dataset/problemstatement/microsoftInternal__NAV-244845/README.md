# [master] [ALL-E] Posting purchase order in partial receipt leads to an rounding issue when posting the invoice when you have Automatic Cost Posting active

## Repro Steps

1) Inventory Setup

Automatic Cost Posting = True
Expected Cost Posting to G/L = True

![Image](./image.png)

Open Inventory Posting Setup
Add an Inventory Account (Interim)
![Image](./image_2.png)

2) Create a new Item

![Image](./image_3.png)

Open General Postin Setup
Add an Account Invt. Accrual Acc (Interim)
![Image](./image_4.png)

3) Create a Purchase Order
Vendor: 10000
Vendor Invoice No.: Any
Item: 1020
Location: Blank
Quantity: 100
Unit Cost: 500,00

![Image](./image_5.png)

4) Post a partial receive  '100/3' = 33,33333 Post -> receive

![Image](./image_6.png)
Do a second partial receive with the same Quantity
Post the third partial receive with the Rest Quantity: 33,33334

5)Post the purchase invoice
Post -> Invoice

6) Open the posted invoice

Open the General Ledger Entries
Home -> Find Entries

![Image](./image_7.png)

ACTUAL RESULT:
The Entires for Account 64140 were adjusted, so that this sums up to 0,00

![Image](./image_8.png)

But for the accounts 64120 and 20110 we have a difference of 0,01
![Image](./image_9.png)

EXPECTED RESULT:
The entries for Account 64120 and 20110 should summ up to 0,00 as well:

In BC 14 was it as expected:
see description
