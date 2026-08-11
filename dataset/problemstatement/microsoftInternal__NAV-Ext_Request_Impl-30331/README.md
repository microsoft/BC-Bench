# Extensibility request: override the confirmation question in codeunit 1303 "Correct Posted Sales Invoice".CreateCreditMemoCopyDocument

## Why do you need this change?

With an earlier request (shipped in 28.2), an extension can change what happens to the originating sales
order's quantities when a "Create Corrective Cr. Memo" action is called for a posted sales invoice. When an
extension changes that behavior, the standard confirmation text becomes inaccurate, because it states that
the original quantities will be reverted. The existing `OnBeforeCreateCreditMemoCopyDocument` event has no
`IsHandled`/text parameter, so it cannot be used to adjust this specific `Confirm`.

## Describe the request

In procedure `CreateCreditMemoCopyDocument` of codeunit 1303 "Correct Posted Sales Invoice", move the
confirmation text into a local variable, raise a new integration event that lets subscribers override it,
and then pass that variable to `Confirm`:

```al
if not SalesHdr.IsEmpty then begin
    ConfirmQuestion := CreateCreditMemoQst;
    OnCreateCreditMemoCopyDocumentOnBeforeConfirm(SalesInvoiceHeader, SalesHdr, ConfirmQuestion);
    if not Confirm(ConfirmQuestion) then
        exit(false);
end;

[IntegrationEvent(false, false)]
local procedure OnCreateCreditMemoCopyDocumentOnBeforeConfirm(var SalesInvoiceHeader: Record "Sales Invoice Header"; var SalesHeader: Record "Sales Header"; var ConfirmQuestion: Text)
begin
end;
```

## Scope

- File: `CorrectPostedSalesInvoice.Codeunit.al`
- This codeunit is present in the W1, APAC and ES layers (each keeps its own copy). The identical change
  must be applied to all three layer files (W1, APAC, ES).
