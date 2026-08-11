# Extensibility request: event in "Item Tracking Management".SplitPostedWhseRcptLine when no Whse. Item Entry Relation is found

## Why do you need this change?

We need an additional event in codeunit 6500 "Item Tracking Management". The event placement and logic
should be the same as within the procedure `SplitInternalPutAwayLine` — specifically, the event
`OnSplitInternalPutAwayLineOnNotFindWhseItemTrackingLine`.

We need this event to perform custom splitting.

This was already requested previously, but the whole request was declined because of the event inside
the loop. We agree that custom splitting can be handled before the loop, but we still need the new event
in case Warehouse Item Entry Relation is not found.

**Performance Considerations:**
The proposed event `OnSplitPostedWhseReceiptLineOnNotFindWhseItemEntryRelation` is located outside the
`repeat...until` loop, in the `else` branch that executes only when `WhseItemEntryRelation.FindSet()`
returns no records for the given posted warehouse receipt line. It fires at most once per call to
`SplitPostedWhseRcptLine`, not once per iteration, so the added overhead is negligible — a single
conditional check and, if no subscriber is attached, no additional cost at all.

**Multi-Extension Interaction:**
The event follows the standard `IsHandled` pattern already used elsewhere in this codeunit (e.g.
`OnBeforeSplitPostedWhseReceiptLine`). Once any subscriber sets `IsHandled` to `true`, the base logic
(`TempPostedWhseRcptLine := PostedWhseRcptLine; TempPostedWhseRcptLine.Insert();`) is skipped.

## Describe the request

Add a new integration event in `SplitPostedWhseRcptLine` when `WhseItemEntryRelation.FindSet()` does not
find any records, using the `IsHandled` pattern before the default insert of `PostedWhseRcptLine` into
`TempPostedWhseRcptLine`.

Location in the `SplitPostedWhseRcptLine()` procedure:

```al
                end;
            until WhseItemEntryRelation.Next() = 0
        else begin
            IsHandled := false;
            OnSplitPostedWhseReceiptLineOnNotFindWhseItemEntryRelation(PostedWhseRcptLine, TempPostedWhseRcptLine, IsHandled);
            if not IsHandled then begin
                TempPostedWhseRcptLine := PostedWhseRcptLine;
                TempPostedWhseRcptLine.Insert();
            end;
        end;

        OnAfterSplitPostedWhseReceiptLine(PostedWhseRcptLine, TempPostedWhseRcptLine);
    end;
```

Event publisher (add at the end of the codeunit with the other events):

```al
[IntegrationEvent(false, false)]
local procedure OnSplitPostedWhseReceiptLineOnNotFindWhseItemEntryRelation(PostedWhseRcptLine: Record "Posted Whse. Receipt Line"; var TempPostedWhseRcptLine: Record "Posted Whse. Receipt Line" temporary; var IsHandled: Boolean)
begin
end;
```

## Scope

- File: `ItemTrackingManagement.Codeunit.al`
- This codeunit exists only in the W1 base layer, so the change lives in W1 alone (no country/region
  layer counterparts to propagate to).
