# [For AI fix] Matched Order Lines functionality could lead to inconsistent information if we deal with very similar Purchase Orders.

## Repro Steps

1- Post 'Receive' two exact purchase orders with the same Vendor, location, item and quantity:

![Image](./image_1.png)

![Image](./image_2.png)

![Image](./image_3.png)

2- Open the Posted Purchase Receipt lines and you will see that there is two Receipts document '107245' that is related to the Purchase order '106035' and '107246' that is related to purchase order '106036'

![Image](./image_4.png)

3- Open a new Purchase Invoice and select the vendor that has been used in the Purchase Orders and then click on 'Line' > 'Functions' > 'Get Receipt Lines':
![Image](./image_5.png)

4- Select one of the two posted purchase receipt. In this example I have selected '107245'
![Image](./image_6.png)

5- Click on 'Related Information' > 'Matched Order Lines'
![Image](./image_7.png)

6- Click on 'Get Order Lines':
![Image](./image_8.png)

7- Select the order that is **not** related to the previously selected Posted Purchase Receipt. Since receipt **107245** is linked to order **106035**, so select order **106036** in this step. (The user is not doing this intentionally. However, this mistake can occur because the two purchase orders are identical.)
![Image](./image_9.png)

![Image](./image_10.png)

8- Post this purchase invoice.

9- Open the two purchase orders that were created in the first step:
![Image](./image_11.png)

![Image](./image_12.png)

As you can see, both items appear as invoiced, even though only one item has actually been invoiced.


10- Open the 'Posted Purchase Receipt Lines':
![Image](./image_13.png)

As shown, only one item has been invoiced, despite the purchase order indicating that both items were invoiced.

**Expected Outcome:**

The system should prevent the user from selecting a purchase order that is not related to the Posted Purchase Receipt that was selected on the Purchase Invoice.


**Actual Outcome:**
The system is not preventing the user from selecting a purchase order that is not related to the Posted Purchase Receipt that was selected on the Purchase Invoice.

**Troubleshooting Actions Taken:**
We have replicated the issue on our side and we couldn't find any similar reported issues

**Did the partner reproduce the issue in a Sandbox without extensions?**Yes

## Description

Matched Order Lines functionality could lead to inconsistent information if we deal with very similar Purchase Orders.
