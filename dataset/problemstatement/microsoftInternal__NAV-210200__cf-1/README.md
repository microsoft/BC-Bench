# Title: Using Get Std. Service Codes. on a Sales Order to pull in an Item that has Reserve = Always into the Service Line, there is no Reservation.
## Repro Steps:
1.  **Item Card**
![Item Card Step1](./item_card_step1.png)
2. Create Positive Adjustment Item Journal and for BLUE Location for this item for 5 qty and post it.
3. Create Service Item for Customer 30000.
![Service Item Card Step3](./service_item_card_step3.png)
4- Create standard service code for the item:
![Standard Service Code Card Step4](./standard_service_code_card_step4.png)
5- Create service order for BLUE Location, and fill in the fields as following.  Then click on Functions > Get Std. Service Codes then select the ones that you created: 
![Service Card Step5](./service_card_step5.png)
![Standard Serv Item Step5](./standard_serv_item_step5.png)
6- Open the service lines and **filter by ALL** so that you can see the Code you pulled in:
![Service Order Step6](./service_order_step6.png)
![Service Line Step6](./service_line_step6.png)

**The actual result:**
The item was added with the correct quantity, but 'Reserved Quantity' = blank (You will need to add this field via Personalization):
![Result](./result.png)

**The expected result:**
The 'Reserve Quantity' = 5 
​If you were to type 2 over in the quantity field, it will then Auto Reserve.

## Description:
