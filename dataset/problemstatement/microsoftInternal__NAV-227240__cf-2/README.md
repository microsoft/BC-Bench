# Title: The due date is not updated if the reminder has already been issued

## Description:

The Reminder/Fin. Charge Entry due date should not be updated after the reminder has been issued. Once a reminder is issued, its due date becomes immutable regardless of changes to the Customer Ledger Entry due date.

## Repro Steps:

1. Create a customer with reminder terms configured.
2. Create and post a sales invoice.
3. Create and issue a reminder for the customer.
4. Change the Customer Ledger Entry due date (forward or backward) → the Reminder/Fin. Charge Entry due date should **NOT** update because the reminder has already been issued.

## Expected Behavior:

- If the reminder has been issued, no due date updates should propagate to the Reminder/Fin. Charge Entry, regardless of direction.
- Only non-issued reminders should have their due dates synchronized with Customer Ledger Entry changes.
