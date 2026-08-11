# Extensibility request: OnBeforeOnRunOnCheckWarehouse event in codeunit 99000760 "Mfg. Item Jnl. Check Line"

## Why do you need this change?

We currently have two subscribers associated with the `OnRunOnCheckWarehouse` publisher event: one provided
by the standard Microsoft application and another implemented in our extension. When posting Consumption
transactions through our application, the warehouse validation logic executed in the local procedure
`OnRunOnCheckWarehouse` of codeunit 99000760 "Mfg. Item Jnl. Check Line" is preventing further processing,
as it is called by the MS standard event.

To handle this scenario, we require a handler event to conditionally bypass this validation logic for
transactions from our application. Providing an extensibility point (publisher event) within
`OnRunOnCheckWarehouse` would allow extensions to skip the standard validation when necessary, while
preserving the existing behavior for all other scenarios.

## Describe the request

Introduce a new publisher `OnBeforeOnRunOnCheckWarehouse` event at the start of procedure
`OnRunOnCheckWarehouse` that allows extensions to skip the standard validation logic when required, using
the `IsHandled` pattern with an early exit:

```al
IsHandled := false;
OnBeforeOnRunOnCheckWarehouse(ItemJournalLine, CalledFromAdjustment, CalledFromInvtPutawayPick, IsHandled);
if IsHandled then
    exit;
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeOnRunOnCheckWarehouse(var ItemJournalLine: Record "Item Journal Line"; CalledFromAdjustment: Boolean; CalledFromInvtPutawayPick: Boolean; var IsHandled: Boolean)
begin
end;
```

## Scope

- File: `MfgItemJnlCheckLine.Codeunit.al`
- This codeunit exists in both the W1 base layer and the IT layer (which keeps its own copy). The identical
  change must be applied to both the W1 and IT layer files.
