# Codeunit 5826 "Matched Order Line Mgmt." - Procedures GetPurchaseOrderLines and ShowMatchedInvoiceLines  from internal to public

### Why do you need this change?

We would like to use this functionality in our document pages.

### Describe the request

Can the codeunit and procedures please be set from internal to public.

```
codeunit 5826 "Matched Order Line Mgmt."
{
    Access = Public;
...
    procedure GetPurchaseOrderLines(PurchaseLine: Record "Purchase Line")
...
    procedure ShowMatchedInvoiceLines(PurchaseLineOrder: Record "Purchase Line")
```
