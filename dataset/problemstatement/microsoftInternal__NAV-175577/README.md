# Title: [Job Task Billing] Job Create Sales Invoice (1093, Report Request) - ignores Bill To / sell To/ Inv Curr in Job Task
## Repro Steps:
Create new projects:
SellTo = 10000, BillTo = 20000, Billing = Multiple Customers.

Add 4 job tasks:
JT1: SellTo 10000, BillTo 10000
JT2: SellTo 10000, BillTo 20000

Add to each JT the line of type billable with Item (any), Qty / price - any.

Run
    Job Create Sales Invoice (1093, Report Request)
    Filter by Job No.

    Result - 2 invoice created.
    Expected 1 invoices to be created (if SellTo, BillTo, InvCurr Code are same, these tasks should be combined into one invoice)

    Use payment method/external doc no,.. from the first job tasks

## Description:
