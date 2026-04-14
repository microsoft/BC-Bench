# Title: Item Charge throws error when pulled into Sales Return Order when Default Qty. to Ship is set to 'Blank' on Sales & Rec Setup
## Repro Steps:
Item Charge validation should not depend on Default Quantity to Ship setup. The Qty. to Invoice should always be validated.

![Sales Receivables Setup](./sales-receivables-setup.png)

The validation is always enforced regardless of the setup configuration.

![Item Charge Assignment](./item-charge-assignment.png)
## Description:
Item Charge Qty. to Invoice validation does not depend on setup configuration.
