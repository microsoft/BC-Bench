# Extensibility request: add parameters to OnCheckExpirationDateOnBeforeAssignExpirationDate in codeunit 22 "Item Jnl.-Post Line"

## Why do you need this change?

I would like 3 additional parameters added to the `OnCheckExpirationDateOnBeforeAssignExpirationDate` event
so that I can create similar code/logic to the standard code (although slightly modified) and handle the
event using the existing `IsHandled` parameter.

Note: as this is an integration event, adding extra parameters is not a breaking change, and existing
subscribers will be unaffected.

## Describe the request

Add the following 3 parameters to `OnCheckExpirationDateOnBeforeAssignExpirationDate` (raised in
`CheckExpirationDate`) and pass them from the caller:

```
GlobalItemTrackingCode
ItemJnlLine2
SignFactor
```

Current event signature:

```al
[IntegrationEvent(false, false)]
local procedure OnCheckExpirationDateOnBeforeAssignExpirationDate(var TempTrackingSpecification: Record "Tracking Specification" temporary; ExistingExpirationDate: Date; var IsHandled: Boolean)
begin
end;
```

New event signature:

```al
[IntegrationEvent(false, false)]
local procedure OnCheckExpirationDateOnBeforeAssignExpirationDate(var TempTrackingSpecification: Record "Tracking Specification" temporary; ExistingExpirationDate: Date; GlobalItemTrackingCode: Record "Item Tracking Code"; ItemJnlLine2: Record "Item Journal Line"; SignFactor: Integer; var IsHandled: Boolean)
begin
end;
```

## Scope

- File: `ItemJnlPostLine.Codeunit.al`
- This codeunit is present in the W1, APAC, CH, ES, IT and RU layers (each keeps its own copy). The
  identical change must be applied to all six layer files (W1, APAC, CH, ES, IT, RU).
