# Extensibility request: override the confirmation question in codeunit 1322 "Correct PstdSalesInv (Yes/No)".CancelPostedInvoiceAndOpenSalesOrder

## Why do you need this change?

Following an earlier request (shipped in 28.2), an extension can now change what happens to the originating
sales order's quantities when a posted sales invoice is corrected/cancelled from the page actions. When that
behavior is changed, the standard confirmation text shown to the user before the action becomes inaccurate,
because it states that the original quantities will be reverted. We need a way to override the confirmation
question text without duplicating this procedure's logic.

The confirmation is raised in `CancelPostedInvoiceAndOpenSalesOrder` of codeunit 1322
"Correct PstdSalesInv (Yes/No)" via `ConfirmManagement.GetResponse(CorrectPostedInvoiceFromSingleOrderQst, ...)`.

## Describe the request

Introduce the confirmation text into a local variable, raise a new integration event that lets subscribers
override it, and then pass that variable to `ConfirmManagement.GetResponse`:

```al
local procedure CancelPostedInvoiceAndOpenSalesOrder(var SalesInvoiceHeader: Record "Sales Invoice Header"; var SalesHeader: Record "Sales Header"): Boolean
var
    ConfirmManagement: Codeunit "Confirm Management";
    CorrectPostedSalesInvoice: Codeunit "Correct Posted Sales Invoice";
    IsHandled: Boolean;
    ConfirmQuestion: Text;
begin
    ConfirmQuestion := CorrectPostedInvoiceFromSingleOrderQst;
    OnCancelPostedInvoiceAndOpenSalesOrderOnBeforeConfirm(SalesInvoiceHeader, SalesHeader, ConfirmQuestion);
    if ConfirmManagement.GetResponse(ConfirmQuestion, false) then begin
        ...
    end;
end;

[IntegrationEvent(false, false)]
local procedure OnCancelPostedInvoiceAndOpenSalesOrderOnBeforeConfirm(var SalesInvoiceHeader: Record "Sales Invoice Header"; var SalesHeader: Record "Sales Header"; var ConfirmQuestion: Text)
begin
end;
```

## Scope

- File: `CorrectPstdSalesInvYesNo.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
