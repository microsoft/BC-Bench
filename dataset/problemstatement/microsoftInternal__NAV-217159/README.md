Title: [Master][ALL-E] Message when using "Create corrective Credit Memo" on a partial sales or purchase invoice related to an existing Order needs to inform that the Order Quantities will be changed.
Repro Steps:
Search for Sales Orders Create a new OrderCustomer: 10000Item: 70000Quantity: 10Quantity to ship: 5Post ship and invoice Open the created Sales OrderOn the Sales order -> Order InvoicesSelect the invoice -> Cancel ACTUAL RESULT: No Message and a Credit Memo was createdEXPECTED RESULT:A message should appear when the Sales Order still existsThe invoice was posted from an order. A Sales Credit memo will be created which you complete and post manually. The quantities will be corrected in the existing Sales Order.Do you want to continue? Additional Information:Same for the purchase side
Description:

