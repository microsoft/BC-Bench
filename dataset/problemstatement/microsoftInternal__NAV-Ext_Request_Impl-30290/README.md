# Extensibility request: OnBeforeUpdateSetupOnBillToCustomerChangeInSalesHeader event in table 36 "Sales Header"

## Why do you need this change?

We need to bypass the standard Microsoft logic in this procedure because we have a separate feature that
already handles the assignment of the VAT Registration No. and the relevant posting groups. Without an
`IsHandled` pattern, the Microsoft logic is always executed and may overwrite or conflict with the values
set by our own feature.

## Describe the request

Add an `OnBeforeUpdateSetupOnBillToCustomerChangeInSalesHeader` integration event before calling
`AltCustVATRegFacade.UpdateSetupOnBillToCustomerChangeInSalesHeader(Rec, xRec, BillToCustomer)` in procedure
`SetBillToCustomerAddressFieldsFromCustomer`. The event should provide an `IsHandled` parameter so
subscribers can skip the mentioned call when they handle the logic themselves.

```al
IsHandled := false;
OnBeforeUpdateSetupOnBillToCustomerChangeInSalesHeader(Rec, BillToCustomer, IsHandled);
if not IsHandled then
    AltCustVATRegFacade.UpdateSetupOnBillToCustomerChangeInSalesHeader(Rec, xRec, BillToCustomer);
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeUpdateSetupOnBillToCustomerChangeInSalesHeader(var SalesHeader: Record "Sales Header"; BillToCustomer: Record Customer; var IsHandled: Boolean)
begin
end;
```

There are already three events in this procedure, but none lets me skip only the
`AltCustVATRegFacade.UpdateSetupOnBillToCustomerChangeInSalesHeader` call while keeping the rest of the
standard logic.

## Scope

- File: `SalesHeader.Table.al`
- This table is present in 15 layers (W1, APAC, BE, CH, CZ, ES, FI, FR, GB, IT, NA, NL, NO, RU, SE), each
  keeping its own copy. The identical change must be applied to all 15 layer files.
