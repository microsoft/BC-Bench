# Extensibility request: override the confirmation question in codeunit 1323 "Cancel PstdSalesInv (Yes/No)".CancelInvoice

## Why do you need this change?

With an earlier request (shipped in 28.2), an extension can change what happens to the originating sales
order's quantities when a posted invoice is corrected/cancelled from the page actions. The standard
confirmation text before the cancellation becomes inaccurate when that behavior is overridden, because it
states that the original quantities will be reverted. Currently there is no event before this specific
`Confirm` call to adjust it (the existing `OnCancelInvoiceOnBeforeTestCorrectInvoiceIsAllowed` event only
gates the validation check, not this message).

## Describe the request

In procedure `CancelInvoice` of codeunit 1323 "Cancel PstdSalesInv (Yes/No)", move the confirmation text
into a local variable, raise a new integration event that lets subscribers override it, and then pass that
variable to `Confirm`:

```al
ConfirmQuestion := CancelPostedInvoiceQst;
OnCancelInvoiceOnBeforeConfirm(SalesInvoiceHeader, ConfirmQuestion);
if Confirm(ConfirmQuestion) then
    ...

[IntegrationEvent(false, false)]
local procedure OnCancelInvoiceOnBeforeConfirm(var SalesInvoiceHeader: Record "Sales Invoice Header"; var ConfirmQuestion: Text)
begin
end;
```

## Scope

- File: `CancelPstdSalesInvYesNo.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
