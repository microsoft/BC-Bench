Title: [Shopify] Exported invoice - when copied it should clear Shopify Order Id (and Shopify Order No).
Repro Steps:
BC Connected to Shopify
Payment terms are imported and FIXED is marked as default.
Enable Invoice Sync in the ORders fast tab.

Create new customer with email and export it to Shopify (Customers -> Add Customer)
Create sales invoicefor that customer with any item, qty 1, price 100. Post.
Run Sync Posted Invoices.
Expected that this invoice is exported to Shopify.

Create new invoice, choose Copy Document.
Select the posted sales invoice, choose Copy Header = yes, recalculate Lines = false.
Post invoice.
Run sync - this invoice is not included.
IF you choose Update Document - you can see that it already has Shopify Order Id populated with order exported to Shopify earlier.
This field is the reason why this invoice is ignored.

We need to adjust "Copy Document" logic to clean up Shopify ORder Id field.
Description:
