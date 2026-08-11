# Extensibility request: add a temporary Warehouse Activity Line parameter to OnBeforeCreateWhseActivHeader in codeunit 7312 "Create Pick"

## Why do you need this change?

Add a parameter `TempWhseActivLine: Record "Warehouse Activity Line" temporary` as a `var` in the event
`OnBeforeCreateWhseActivHeader` of codeunit 7312 "Create Pick".

To support adding new items from an order to an existing warehouse pick for Sales Orders, Transfer Orders,
and Purchase Return Orders, we need access to a temporary instance of the Warehouse Activity Line record
during the pick creation process. Currently the `OnBeforeCreateWhseActivHeader()` event does not provide a
mechanism to pass or manipulate temporary warehouse activity lines. This will allow custom logic to prepare
and manage additional lines before the warehouse activity header is created.

## Describe the request

Enhance the existing `OnBeforeCreateWhseActivHeader` publisher signature by adding a
`var TempWhseActivLine: Record "Warehouse Activity Line" temporary` parameter, and pass the temporary
record instance when the event is raised in `CreateWhseActivHeader`:

```al
IsHandled := false;
OnBeforeCreateWhseActivHeader(CurrWarehouseActivityHeader, TempWarehouseActivityLine, LocationCode, FirstWhseDocNo, LastWhseDocNo, NoOfSourceDoc, NoOfLines, WhseDocCreated, IsHandled);
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeCreateWhseActivHeader(var CurrWarehouseActivityHeader: Record "Warehouse Activity Header"; var TempWhseActivLine: Record "Warehouse Activity Line" temporary; LocationCode: Code[10]; var FirstWhseDocNo: Code[20]; var LastWhseDocNo: Code[20]; var NoOfSourceDoc: Integer; var NoOfLines: Integer; var WhseDocCreated: Boolean; var IsHandled: Boolean)
begin
end;
```

## Scope

- File: `CreatePick.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
