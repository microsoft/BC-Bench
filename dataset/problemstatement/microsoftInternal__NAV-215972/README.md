# Title: Reservation of an Item possible with in a Transfer order if the item is set to reserve=never
## Repro Steps:
1- Create an item with reserve = Never:
![Item Card Step1](./item_card_step1.png)
2- Add amount of 100 to location GELB:
![Adjust Inventory Step2](./adjust_inventory_step2.png)
3- Create a transfer order:
![Transfer Order Step3](./transfer_order_step3.png)
4- In the lines fasttab, click reserve and reserve the amount outbound:
![Reservsation Step4](./reservsation_step4.png)
The system will allow the reservation of the amount.
I tested the scenario for a sales order and got the below error message:
![Error Message Step4](./error_message_step4.png)

Expected behavior: The system should show the same error message in the transfer order.

## Description:
