# [master] [ALL-E] Drop shipment undo receipt fails for service and non-inventory items.

## Repro Steps

We identified an issue when using the \*\*Drop Shipment\*\* functionality with an item of type \*\*Service\*\*.
After posting the Purchase Receipt and the corresponding Sales Shipment is automatically created, it is not possible to reverse the transaction using either \*\*Undo Receipt\*\* or \*\*Undo Shipment\*\*.
\*\*Steps to Reproduce\*\*
\*\*1. Create a Sales Order\*\*
Create a Sales Order containing:
\* An item of type \*\*Service\*\*;
\* The \*\*Drop Shipment\*\* field enabled on the sales line
![Picture1.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/5e960437-9d6e-4c10-85ec-60b8f2ee1e1f?fileName=Picture1.png)
![Picture2.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/c0b14cd7-2100-47e1-af98-0ac62c4b50a7?fileName=Picture2.png)
\*\*2. Create the Purchase Order through the Requisition Worksheet\*\*
Use the \*\*Get Sales Orders\*\* action in the Requisition Worksheet to generate the corresponding Drop Shipment Purchase Order.
\*\*3. Create the Purchase Order\*\*
Create the Purchase Order suggested by the Requisition Worksheet.
\*\*4. Post the Purchase Receipt\*\*
Post the receipt of the Purchase Order line.
\*\*Result:\*\*
\* The Purchase Receipt is posted successfully.
\* The system automatically posts the corresponding Sales Shipment for the linked Sales Order line, as expected in a Drop Shipment scenario.
\*\*5. Attempt to Undo the Purchase Receipt\*\*
Navigate to the \*\*Posted Purchase Receipt\*\* and execute the \*\*Undo Receipt\*\* action.
\*\*Result:\*\*
\* The operation fails and the receipt cannot be undone.
![Picture3.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/ddd20442-73c8-41c3-9211-13fe3d910e77?fileName=Picture3.png)
![Picture4.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/70a59ef6-2d4e-4752-980b-78660cc8cd17?fileName=Picture4.png)
\*\*6. Attempt to Undo the Sales Shipment\*\*
Navigate to the \*\*Posted Sales Shipment\*\* and execute the \*\*Undo Shipment\*\* action.
\*\*Result:\*\*
\* The operation fails and the shipment cannot be undone.
![Picture5.png](https://dev.azure.com/dynamicssmb2/1fcb79e7-ab07-432a-a3c6-6cf5a88ba4a5/\_apis/wit/attachments/f83210d0-8a05-4aa9-bed8-fbac9cfe178f?fileName=Picture5.png)
\*\*Expected Result\*\*
\* The system should allow the use of the standard \*\*Undo Receipt\*\* and \*\*Undo Shipment\*\* functionalities to reverse the transaction; or
\*\*Actual Result\*\*
When a \*\*Service\*\* item is used in a Drop Shipment process:
\* The Purchase Receipt is successfully posted.
\* The corresponding Sales Shipment is automatically posted.
\* Neither \*\*Undo Receipt\*\* nor \*\*Undo Shipment\*\* can be completed, preventing the reversal of the transaction.
