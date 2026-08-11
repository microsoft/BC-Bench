# Extensibility request: OnAfterCalcAvailableQtyBase event in table 7326 "Whse. Worksheet Line"

## Why do you need this change?

I need to be able to adjust the quantity that is calculated as being available (we have some stock
ring-fencing customisations). I.e. I want to be able to perform the usual availability calculation and
then reduce it by the quantity that has been ring-fenced.

There is an `OnBeforeCalcAvailableQtyBase()` event with an `IsHandled` property, and I considered using
it by replicating the Microsoft availability calculation code and then adding my own — not ideal. I am
actually unable to use it because I would need to replicate Microsoft code that calls
`CreatePick.CalcTotalAvailQtyToPickForDirectedPutAwayPick(...)`, and that procedure has been marked
**Internal**, so it cannot be called from an extension.

A much better option would be to have an `OnAfterCalcAvailableQtyBase()` event at the end of the
procedure where I could adjust the calculated available quantity.

## Describe the request

Add a new `OnAfterCalcAvailableQtyBase()` integration event called at the end of the
`CalcAvailableQtyBase()` procedure in table 7326 "Whse. Worksheet Line", so extensions can adjust the
final calculated `AvailableQty`.

Location at the end of `CalcAvailableQtyBase()`:

```al
            AvailableQty := AvailQtyBase - QtyAssgndOnWkshBase + AssignedQtyOnReservedLines();
        end;

        OnAfterCalcAvailableQtyBase(Rec, AvailableQty);
    end;
```

Event publisher (add with the other events):

```al
[IntegrationEvent(false, false)]
local procedure OnAfterCalcAvailableQtyBase(var WhseWorksheetLine: Record "Whse. Worksheet Line"; var AvailableQty: Decimal)
begin
end;
```

## Scope

- File: `WhseWorksheetLine.Table.al`
- This table exists only in the W1 base layer, so the change lives in W1 alone (no country/region layer
  counterparts to propagate to).
