Title: [Payables Agent] Item reference search does not respect starting and ending date
Repro Steps:

Description:
We do not support these fields when we search for item reference Repro: Create item reference, specify starting and ending date Have a PDF with dates outside of the item reference period Handle PDF through the agent Actual result: Item reference is picked Expected result: We should not consider the item reference that is not aligned with the date of the invoice
