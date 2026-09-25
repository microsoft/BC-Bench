# Closed subscription lines prevent changing the contract customer

## Environment

- Business Central with the Subscription Billing app enabled.
- A company with two customers and an item configured for subscription billing.

## Reproduction steps

1. Open **Customer Subscription Contracts** and create a contract for the first customer.
2. Add an item contract line with its linked subscription line.
3. Set the subscription line's **Subscription Line End Date** to a past date, for example `31 January 2026`.
4. Create and post billing documents until the subscription line is fully invoiced through its end date.
5. On the customer subscription contract, run **Update Subscription Line Dates**.
6. Verify that the contract line has **Closed** set to **Yes** and is shown under **Closed Lines**.
7. Change **Sell-to Customer No.** on the contract header to the second customer.
8. Repeat the scenario by changing **Bill-to Customer No.** if validating both fields.

## Expected behavior

The Sell-to or Bill-to customer is changed successfully. Closed subscription lines do not prevent a header-level customer change.

## Actual behavior

The customer change is blocked with this error:

> Subscription Lines for closed contract lines may not be edited. Remove the "Finished" indicator in the contract to be able to edit the Subscription Line.
