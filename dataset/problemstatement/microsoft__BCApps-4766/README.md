# Inconsitent data when changing item in manually changing contract line [SubscriptionBilling]

### Describe the issue

When the item no. is changed in a manually created contract line, the connection to the contract persists in the subscription line. This leads to the subscription line being invoiced although it should not have a connection to a contract any longer and should therefore not be considered for invoicing.

### Expected behavior

Sales Invoice Lines should be created only for Contract Lines that exist in the Contract.

### Steps to reproduce

- Create three new items with Subscription Option=Sales with Subscription, no subscription package assigned
- Create a new Customer Subscription Contract and add lines for items No. 1 and No. 2 manually incl. further required data for billing.
- Change item No. 2 with item No. 3.
- Create contract invoice
- Result: all three items are considered
- Check subscription for item No. 2
- Result: In the subscription line, field "Subscription Contract No." still contains the former contract no. although the subscription line is no longer part of that contract.

### Additional context

In the subscription line, the connection to the contract (line) should be revoked when the no. (item or GL account) is changed.
