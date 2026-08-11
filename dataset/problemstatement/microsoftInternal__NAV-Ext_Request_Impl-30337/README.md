# Extensibility request: replaceable Source Type = Item processing in codeunit 99000787 "Create Prod. Order Lines"

## Why do you need this change?

We need a new event in the `CreateProdOrderLine` procedure to allow partners to completely replace the
standard processing of the `Source Type = Item` branch under specific business conditions.

Our customization needs to:

- execute an alternative production order line creation process;
- determine the value of the `ErrorOccured` parameter according to custom logic;
- prevent the standard item-line creation from executing afterwards.

The existing event `OnCreateProdOrderLineOnBeforeInitProdOrderLine(var InsertNew: Boolean)` is useful for
influencing the standard flow, but it is intentionally not designed to replace it. It does not provide an
`IsHandled` parameter to bypass the standard processing, nor access to the `ErrorOccured` parameter.

### Why IsHandled is required

Under specific business conditions our extension needs to completely replace the standard
`Source Type = Item` implementation. If the standard code continues executing after our custom logic, the
production order line would be initialized and inserted twice, and the value assigned to `ErrorOccured` by
the custom implementation could be overwritten. An `IsHandled` pattern is therefore required so subscribers
can intentionally replace the standard implementation.

### Why ErrorOccured is required

The subscriber must be able to set `ErrorOccured` because it represents the outcome of the production order
line creation. When replacing the standard implementation, the extension performs its own validations and
line creation and must be able to report whether the custom process succeeded or failed.

## Describe the request

In procedure `CreateProdOrderLine` of codeunit 99000787 "Create Prod. Order Lines" we request a new
integration event, for example:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeCreateProdOrderLineItem(
    var IsHandled: Boolean;
    var ErrorOccured: Boolean;
    ProdOrder: Record "Production Order")
begin
end;
```

The event should be raised at the start of the `Source Type = Item` branch, guarding the standard
item-line creation with the `IsHandled` flag so that a subscriber can replace it and report the outcome via
`ErrorOccured`.

### Refactoring acceptance

We fully accept refactoring the current `Source Type = Item` implementation into a dedicated local
procedure if this better aligns with the extensibility guidelines. The proposed event can be raised
immediately before an extracted helper procedure containing the existing standard item-line creation logic,
for example:

```al
ProdOrder."Source Type"::Item:
    begin
        IsHandled := false;
        OnBeforeCreateProdOrderLineItem(IsHandled, ErrorOccured, ProdOrder);
        if not IsHandled then
            CreateProdOrderLineFromItem(ProdOrder, VariantCode, ErrorOccured);
    end;
```

where `CreateProdOrderLineFromItem(...)` contains the current standard implementation
(`InitProdOrderLine`, field initialization, quantity validation, dimension copying,
`OnBeforeProdOrderLineInsert`, record insertion, and propagation of `ErrorOccured` through
`ProdOrderLine.HasErrorOccured()`). This refactoring does not change the intent of the request.

## Scope

- File: `CreateProdOrderLines.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
