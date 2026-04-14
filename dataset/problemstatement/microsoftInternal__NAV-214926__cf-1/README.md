# Title: Customer Card Statistics Total tripled — only deduct for Released invoices
## Repro Steps:
1. Create a new Customer
2. Create inventory for an item (10 PCS)
3. Create a Sales Order for 10 PCS at a known unit price
4. Post the Sales Order with Ship only (no invoice)
5. Create a new Sales Invoice, use Get Shipment Lines, and **Release** it
6. Open the Customer Card and check the FactBox statistics

Result: Total ($) shows the amount tripled because Shipped Not Invoiced, Outstanding Invoices, and SalesOutstandingAmountFromShipment all include the same shipment amount.

Expected: Total ($) should equal the Sales Line "Amount Including VAT". The fix should only deduct shipment-derived amounts from Outstanding Invoices when the invoice has Document Status = Released.

## Description:
Variant of NAV-214926 (L2: condition-change). Same test as base (invoice is released). The fix adds a Document Status filter (Released) to GetShippedOutstandingInvoicesAmountLCY, so only released invoices contribute to the deduction. This is a narrower deduction scope than the base fix.
