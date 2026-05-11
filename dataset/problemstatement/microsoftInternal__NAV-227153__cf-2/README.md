# Title: Report Reconcile Customer and Vendor Accounts should only include Payment-type entries when multiple posting groups are used
## Repro Steps:
The "Allow Multiple Posting Groups" is Enabled
![Sales Receivables Setup](./sales_receivables_setup.png)
Different Receivables Account is being assigned to the specific Customer Posting Groups
![Customer Posting Groups](./customer_posting_groups.png)
Alternative Customer Posting Group (TEST) is assigned to DOMESTIC
![Alternative Posting Group](./alternative_posting_group.png)
Allow Multiple Posting Group is also Enabled in the specific Customer Card
![Customer Card](./customer_card.png)
In General Journal, we made 2 payments with posting date (1/1/2027) for the same customer using the Customer Posting Group (Domestic and Test) respectively
![General Journal](./general_journal.png)
In Posted General Journal, we confirmed that the Customer Ledger Entries correctly shows the Customer Posting Groups used in this scenario
![Customer Ledger Entries](./customer_ledger_entries.png)
Using Report ID 33
![Reconcile Customer and Vendor Accounts](./reconcile_customer_and_vendor_accounts.png)

The Report currently considers only the booking group at the debtor/creditor level instead of at the individual debtor/creditor entry level.
![report](./report.png)

**Expected Outcome:**
Individual debtor/creditor entry level should be considered, but only for Payment-type document entries. Invoice and other document types should be excluded from the reconciliation amounts.

**Actual Outcome:**
The Report currently considers only the booking group at the debtor/creditor level instead of at the individual debtor/creditor entry level, and does not distinguish between document types.

**Troubleshooting Actions Taken:**
Replicated the issue and noticed the faulty data

**Did the partner reproduce the issue in a Sandbox without extensions?** Yes

## Description:
The customer reports that Microsoft Standard Report ID 33 produces faulty data starting from Business Central version 20. The report incorrectly considers only the booking group at the debtor/creditor level instead of at the individual debtor/creditor entry level. Furthermore, the reconciliation should only aggregate Payment-type entries, excluding Invoices and other document types from the calculated amounts.
