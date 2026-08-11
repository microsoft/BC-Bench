# Extensibility request: OnBeforeRecreateSalesLine event in table 36 "Sales Header".RecreateSalesLinesHandleSupplementTypes

## Why do you need this change?

We need an event inside the procedure `RecreateSalesLinesHandleSupplementTypes`, in order to be able to add
a custom condition before running `CreateSalesLine()`.

Managing an `IsHandled` parameter is the only way to skip `CreateSalesLine()` (when a particular custom
condition is satisfied) and execute an alternative custom implementation instead. At the moment there are no
existing extensibility points that allow partners to replace the sales line recreation logic at this
specific location.

### Why an IsHandled event is required

Under specific business conditions based on extension fields, our customization must completely replace the
standard `CreateSalesLine()` logic. If the standard code continues to execute after our custom logic, the
standard `CreateSalesLine()` would recreate the sales line again, overwriting the values and relationships
established by the custom implementation. The existing `OnBeforeCreateSalesLine()` event is not sufficient
because it is raised inside `CreateSalesLine()`, after the procedure has already been invoked; we need the
decision point at the caller level, before entering `CreateSalesLine()`.

## Describe the request

In procedure `RecreateSalesLinesHandleSupplementTypes` of table 36 "Sales Header", raise a new `IsHandled`
event immediately before `CreateSalesLine(TempSalesLine)`:

```al
if ShouldCreateSalesLine then begin
    IsHandled := false;
    OnBeforeRecreateSalesLine(IsHandled, SalesLine, TempSalesLine, Rec);
    if not IsHandled then
        CreateSalesLine(TempSalesLine);

    ExtendedTextAdded := false;
    OnAfterRecreateSalesLine(SalesLine, TempSalesLine, Rec);
    ...
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeRecreateSalesLine(var IsHandled: Boolean; var SalesLine: Record "Sales Line"; var TempSalesLine: Record "Sales Line" temporary; var SalesHeader: Record "Sales Header")
begin
end;
```

## Scope

- File: `SalesHeader.Table.al`
- This table is present in 15 layers (W1, APAC, BE, CH, CZ, ES, FI, FR, GB, IT, NA, NL, NO, RU, SE), each
  keeping its own copy. The identical change must be applied to all 15 layer files.
