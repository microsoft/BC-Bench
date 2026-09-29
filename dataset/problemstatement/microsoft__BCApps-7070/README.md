# Customer cannot be changed on a contract with closed subscription lines

## Describe the issue

When a customer contract contains closed subscription lines—lines marked as **Closed = Yes** after invoicing past their end date—changing the **Sell-to Customer** or **Bill-to Customer** on the contract header fails with a blocking error.

This is inconsistent with terminated lines that are not closed (**Closed = No**), which allow the customer to be changed. Users must otherwise reopen each closed line, change the customer, and close every line again.

## Expected behavior

Changing the Sell-to or Bill-to customer on a contract header succeeds regardless of whether closed subscription lines exist. Terminated lines with **Closed = Yes** and **Closed = No** behave identically for a header-level customer change.

## Steps to reproduce

1. Create a customer contract with at least one subscription or contract line.
2. Set the **Subscription Line End Date** to a date in the past, for example `31 January 2026`.
3. Invoice the line fully through its end date.
4. Run **Update Subscription Line Dates**.
5. Verify that the contract line is marked **Closed = Yes** and moved to **Closed Lines**.
6. Change the **Sell-to Customer** or **Bill-to Customer** on the contract header.

The change is blocked with this error:

> Subscription Lines for closed contract lines may not be edited. Remove the "Finished" indicator in the contract to be able to edit the Subscription Line.
