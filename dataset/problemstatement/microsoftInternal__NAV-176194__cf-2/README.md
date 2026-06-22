# Title: Item Charge throws error when pulled into Sales Return Order when Default Qty. to Ship is set to 'Blank' on Sales & Rec Setup
## Repro Steps:
Item Charge should only be validated when Default Qty to Ship is Blank, not when it is non-Blank.

![Sales Receivables Setup](./sales-receivables-setup.png)

The validation condition is inverted: Qty. to Invoice is checked only when setup is Blank.

![Item Charge Assignment](./item-charge-assignment.png)
## Description:
Item Charge Qty. to Invoice validation condition is inverted.
