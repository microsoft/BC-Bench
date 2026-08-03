# Extensibility request: IsHandled event before PrepareJobLine in codeunit 90 "Purch.-Post".PostItemJnlLineJobConsumption

## Why do you need this change?

We need an event before `InvoicePostingInterface.PrepareJobLine(...)` in order to be able to assign a
different value to the field "Qty. to Invoice" according to a particular custom condition, as well as run a
different custom procedure instead of `PrepareJobLine`. At the moment there are no alternative events to
skip the procedure `PrepareJobLine` or run a custom procedure instead when a condition based on custom
fields is satisfied.

### Why an IsHandled event is required

Under particular custom conditions based on extension fields, we must completely replace the standard
`PrepareJobLine` execution with a custom implementation and assign a different value to
`PurchLine."Qty. to Invoice"`. If the standard code continues to execute after our custom logic,
`PrepareJobLine` would run twice or would overwrite the values calculated by our customization. The existing
`OnPostItemJnlLineJobConsumption` / `OnPostItemJnlLineJobConsumptionOnBeforeJobPost` events are raised too
early, and the downstream `OnBeforePostJobOnPurchaseLine` event is raised after `PrepareJobLine` has already
run, so the hook is needed immediately before that call.

## Describe the request

In procedure `PostItemJnlLineJobConsumption` of codeunit 90 "Purch.-Post", raise a new `IsHandled` event
immediately before `InvoicePostingInterface.PrepareJobLine(...)`:

```al
if QtyToBeInvoiced <> 0 then begin
    PurchLine."Qty. to Invoice" := QtyToBeInvoiced;
    IsHandled := false;
    OnBeforePrepareJobLinePrepareJobLine(IsHandled, PurchLine, QtyToBeInvoiced, PurchHeader, PurchLineACY);
    if not IsHandled then
        InvoicePostingInterface.PrepareJobLine(PurchHeader, PurchLine, PurchLineACY);
end;
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforePrepareJobLinePrepareJobLine(var IsHandled: Boolean; var PurchLine: Record "Purchase Line"; QtyToBeInvoiced: Decimal; var PurchHeader: Record "Purchase Header"; var PurchLineACY: Record "Purchase Line")
begin
end;
```

## Scope

- File: `PurchPost.Codeunit.al`
- This codeunit is present in 10 layers (W1, APAC, BE, CH, ES, FI, GB, IT, NA, RU), each keeping its own
  copy. The identical change must be applied to all 10 layer files.
