# Title: Item Charge throws error when pulled into Sales Return Order when Default Qty. to Ship is set to 'Blank' on Sales & Rec Setup
## Repro Steps:
Qty. to Invoice is not required when assigning item charges. The validation should not block the flow.

![Sales Receivables Setup](./sales-receivables-setup.png)

The Item Charge should be successfully assigned regardless of Qty. to Invoice value.

![Item Charge Assignment](./item-charge-assignment.png)
## Description:
Qty. to Invoice validation removed from Item Charge Assignment.
