# [W1][Codeunit][7312][Create Pick] Add integration event OnCreateWhseDocPlaceLineOnBeforeHandleRemainingPickQty in procedure CreateWhseDocPlaceLine

### Why do you need this change?

We need to intercept CreateWhseDocPlaceLine in Codeunit 7312 "Create Pick" inside the repeat loop, after TempWarehouseActivityLine.Delete() removes the current temporary place line and before the if PickQtyBase > 0 then block that merges remaining pick quantity from subsequent temporary lines. The goal is to allow a subscriber to handle the remaining-quantity step in a completely different way and skip the standard merging loop.

The standard code unconditionally enters if PickQtyBase > 0 then begin to merge outstanding quantity from matching temporary lines. There is no hook that lets a subscriber take over this step, for example to set container-linking fields on WarehouseActivityLine and bypass the standard bin-content search that follows.

The existing event OnCreateWhseDocPlaceLineOnAfterTempWhseActivLineSetFilters fires inside the if PickQtyBase > 0 block after the filter setup, which is already too late to skip the entire block. OnCreateWhseDocPlaceLineOnAfterTransferTempWhseActivLineToWhseActivLine fires earlier in the iteration before the source document assignment. No event currently exists between TempWarehouseActivityLine.Delete() and the if PickQtyBase > 0 check.

### Describe the request

Add an integration event OnCreateWhseDocPlaceLineOnBeforeHandleRemainingPickQty in CreateWhseDocPlaceLine in Codeunit 7312 "Create Pick" inside the place-line repeat loop, after TempWarehouseActivityLine.Delete() and before the if PickQtyBase > 0 then block.

```al
TempWarehouseActivityLine.Delete();

IsHandled := false;
OnCreateWhseDocPlaceLineOnBeforeHandleRemainingPickQty( // <---- New Event
    WarehouseActivityLine, PickQty, PickQtyBase, LineNo, IsHandled);
if not IsHandled then
    if PickQtyBase > 0 then begin
        TempWarehouseActivityLine3.Copy(TempWarehouseActivityLine);
        TempWarehouseActivityLine.SetRange(
          "Unit of Measure Code", WarehouseActivityLine."Unit of Measure Code");
        TempWarehouseActivityLine.SetFilter("Line No.", '>%1', TempWarehouseActivityLine."Line No.");
        TempWarehouseActivityLine.SetRange("No.", TempWarehouseActivityLine2."No.");
        TempWarehouseActivityLine.SetRange("Bin Code", WarehouseActivityLine."Bin Code");
        OnCreateWhseDocPlaceLineOnAfterTempWhseActivLineSetFilters(TempWarehouseActivityLine, WarehouseActivityLine);
        if TempWarehouseActivityLine.Find('-') then
            repeat
                ...
            until (TempWarehouseActivityLine.Next() = 0) or (PickQtyBase = 0)
        else
            if TempWarehouseActivityLine.Delete() then;
        TempWarehouseActivityLine.Copy(TempWarehouseActivityLine3);
    end;
```
Event Signature:

```
[IntegrationEvent(false, false)]
local procedure OnCreateWhseDocPlaceLineOnBeforeHandleRemainingPickQty(var WarehouseActivityLine: Record "Warehouse Activity Line"; var PickQty: Decimal; var PickQtyBase: Decimal; LineNo: Integer; var IsHandled: Boolean)
begin
end;
```

Alternatives evaluated: OnCreateWhseDocPlaceLineOnAfterTempWhseActivLineSetFilters fires inside the if PickQtyBase > 0 block after filter setup on the temporary table, which is too late to skip the merging loop entirely. OnCreateWhseDocPlaceLineOnAfterTransferTempWhseActivLineToWhseActivLine fires at the start of the iteration before the delete and does not expose PickQty or PickQtyBase in their post-delete state. No event currently exists between TempWarehouseActivityLine.Delete() and the if PickQtyBase > 0 check in this loop.
