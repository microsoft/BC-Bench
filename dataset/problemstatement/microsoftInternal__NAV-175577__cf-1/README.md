# Title: [Job Task Billing] Job Create Sales Invoice - External Document No. grouping
## Repro Steps:
Create new projects:
SellTo = 10000, BillTo = 20000, Billing = Multiple Customers.

Add 2 job tasks with different External Document No.:
JT1: SellTo 10000, BillTo 20000, External Doc No = EXT-1
JT2: SellTo 10000, BillTo 20000, External Doc No = EXT-2

Expected 2 invoices to be created (if SellTo, BillTo, InvCurr Code, and External Doc. No. are same, these tasks should be combined into one invoice).
External Doc. No. participates in grouping; tasks with different External Doc. No. must not be merged.

## Description:
