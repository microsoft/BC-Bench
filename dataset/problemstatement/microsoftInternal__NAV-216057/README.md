# Title: When recalculating an item in a requisition or planning worksheet with no planning results lead to wrong surplus entries in the reservation table whic are added to the item tracking page.
## Repro Steps:
I tested in BC 25.5 and 26.0 GB and DE Localization.

## Repro Steps:
1. We start with creating a new Item:
![Item Card Step1](./item_card_step1.png) 
With item tracking:
 ![Item Tracking Step1](./item_tracking_step1.png)
And Replenishment System = Purchase and Reordering Policy = Lot-for-Lot
![Item Card 1007test Step1](./item_card_1007test_step1.png)  
2. Create a Sales Order for 100 PCS of the item:
![Sales Order Step2](./sales_order_step2.png)
3. Now plan the item in the requisition worksheet, to meet the demand of the Sales Order:
![Requisition Worksheet Step3](./requisition_worksheet_step3.png)
As expected, the system recommends a Purchase Order
4. Now make the following changes
a. Vendor. No. 10000
b. Change the Quantity from 100 to 150
c. Change the planning flexibility to None (you need to add this field by personalization)
![Requisition Worksheet Step4](./requisition_worksheet_step4.png) 
5. Then enter the item tracking lines and click the "Assign Lot No." option. As expected, the corrected quantity of 150 is filled.
![Item Tracking Lines Step5](./item_tracking_lines_step5.png)
![Item Tracking Lines 1007 Step5](./item_tracking_lines_1007_step5.png) 
6. Now Carry out the Action message and a Purchase Order is created, with the corrected quantity of 150. 
![Carry Out Action Msg Step6](./carry_out_action_msg_step6.png)
7. Open the created Purchase Order
![Purchase Order Step7](./purchase_order_step7.png)
This is how the reservation entry table looks like after the purchase order was created from the Plan worksheet:
![Reservation Entry Step7](./reservation_entry_step7.png)
In the purchase line, navigate to the item tracking line to confirm the lines are available.
![Purchase Order 2 Step7](./purchase_order_2_step7.png)
![Item Tracking Lines Step7](./item_tracking_lines_step7.png)  
8. Now go back to the Requisition Worksheet page and plan the item again.
![Calculate Plan Step8](./calculate_plan_step8.png)
Since earlier we used planning flexibility = none, nothing gets planned, as expected. If we hadn’t, the system would want to reduce the quantity back to 100 to meet the demand exactly.
![Requisition Worksheet Step8](./requisition_worksheet_step8.png) 
9. If we now go back to the purchase order and look into it again, the purchase line itself has not changed as shown below:
![Purchase Order Step9](./purchase_order_step9.png)
Check the reservation entry table again right after you replan the worksheet, you will notice the following below a new surplus entry for 50 pcs was created which is not correct
![Reservation Entry Step9](./reservation_entry_step9.png)
And if you go the item tracking lines on the purchase line, you will notice that the item tracking line has increased by 50pcs we added to the line. (due to the wrong newly created Surplus entry)  This happens again and again, always adding with each calculation. 
![Purchase Order 2 Step9](./purchase_order_2_step9.png)
![Item Tracking Lines Step9](./item_tracking_lines_step9.png) 
10. When we attempt to close the item tracking page, the following message appears:
![Message Step10](./message_step10.png) 

**Actual Result**: The wrongly created surplus entry for the added quantity (50pcs) leads to wrong quantities in the Item tracking lines after replanning the worksheet.

**Expected Result**: These quantities should not be changed and the reservation entries with surplus shouldn't be created.

**Additional information:** Same behavior if you use instead the planning worksheet.
When you post the purchase order everything is posted correctly, and the wrongly created reservation entries are gone.

## Description:
