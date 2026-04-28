# Title: Item Charge throws error when pulled into Sales Return Order when Default Qty. to Ship is set to 'Blank' on Sales & Rec Setup
## Repro Steps:
Qty. to Invoice is validated during processing, not during field validation. The OnValidate trigger should not perform this check.

![Sales Receivables Setup](./sales-receivables-setup.png)

The validation responsibility is shifted from the OnValidate trigger to the processing flow.

![Item Charge Assignment](./item-charge-assignment.png)
## Description:
Item Charge Qty. to Invoice validation moved out of OnValidate trigger.
