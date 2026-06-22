# Title: Show document in Assembly order line page opens the wrong page when the Assembly order line belongs a blanket assembly order.
## Repro Steps:
1- Search for Items
Create a new Item with replenishment system "Assembly":
![Item Card Step1](./item_card_step1.png)
Create a new blanket sales order and add the created item in the lines:
![Blanket Sales Order Step2](./blanket_sales_order_step2.png)
3- Select the below function:
![Select Function Step3](./select_function_step3.png)
4- Add the following line and then select show document: (notice that the blanket sales order was created)
![1002 Test Assembly Step4](./1002_test_assembly_step4.png)
5- Open the page "Blanket Assembly Order" and check if the order was created:
![Blanket Assembly Order Step5](./blanket_assembly_order_step5.png)
6- Search for Assembly order lines
7-Select the Blanket order that we just created and select "Show Document":
![Show Document Step7](./show_document_step7.png)
8- This function will open the Assembly Order page:
![Assembly Order Step8](./assembly_order_step8.png)

Expected result: the routing logic for opening the assembly document should be handled at the page level instead of the table level:
![Result](./result.png)

## Description:
Show document in Assembly order line page opens the wrong page when the Assembly order line belongs a blanket assembly order.
