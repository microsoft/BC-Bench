# Title: When multiple items with extended text are added to a Blanket Sales Order and Make Order is used to create a new Sales Order only the first Extended text is brought over
## Repro Steps:
Issue was tested on BE & DE localizations (it is working fine in GB)
Open item No. 1896-S and open the extended text:
![Item Card](./item_card.png)
Add the below line:
![Extended Text](./extended_text.png)
Repeat this step with another 2 items, but only 2 of the 3 items should have extended text.
Open Blanket sales order and add 3 lines for the 3 items then select make order:
![Blanket sales order](./blanket_sales_order.png)
Open the created sales order and you will find that 1 line for the extended text was created, and the others were not carried out to the sales order:
![Sales Order](./sales_order.png) 

Expected results:
All extended text lines should be carried out to the sales order.

## Description:
Extended text line is not carried out to the Sales order when created from blanket sales order
