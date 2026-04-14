# Title: Customer Card Statistics Total tripled — remove SalesOutstandingAmountFromShipment from formula
## Repro Steps:
1. Create a new Customer
2. Create inventory for an item (10 PCS)
3. Create a Sales Order for 10 PCS at a known unit price
4. Post the Sales Order with Ship only (no invoice)
5. Create a new Sales Invoice, use Get Shipment Lines, and Release it
6. Open the Customer Card and check the FactBox statistics

Result: Total ($) shows the amount tripled because Shipped Not Invoiced, Outstanding Invoices, and SalesOutstandingAmountFromShipment all include the same shipment amount.

Expected: Total ($) should equal the Sales Line "Amount Including VAT". The fix removes SalesOutstandingAmountFromShipment from the formula entirely and only deducts shipment-derived invoice amounts from Outstanding Invoices.

## Description:
Variant of NAV-214926 (L2: record-selection-change). Alternative fix strategy: instead of keeping SalesOutstandingAmountFromShipment in the formula and subtracting two deduction terms (requiring a new query object), this variant removes SalesOutstandingAmountFromShipment entirely and only subtracts ShippedOutstandingInvoicesLCY from Outstanding Invoices. Simpler fix — no new query file needed, only one new procedure.
