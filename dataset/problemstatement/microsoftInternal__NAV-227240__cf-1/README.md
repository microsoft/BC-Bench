# Title: The due date is not updated when the new due date is earlier than the existing reminder due date

## Description:

The Reminder/Fin. Charge Entry due date should only synchronize with the Customer Ledger Entry due date when the new due date is **later** than the existing reminder due date. Backward (earlier) due date changes should be ignored.

## Repro Steps:

1. Create a customer with reminder terms configured.
2. Create and post a sales invoice.
3. Create and issue a reminder for the customer.
4. Change the Customer Ledger Entry due date to a **later** date → the Reminder/Fin. Charge Entry due date should update.
5. Change the Customer Ledger Entry due date to an **earlier** date → the Reminder/Fin. Charge Entry due date should **NOT** update.

## Expected Behavior:

- Forward due date changes (new date > existing reminder due date): Reminder due date updates to match.
- Backward due date changes (new date < existing reminder due date): Reminder due date remains unchanged.
