# Extensibility request: OnBeforeCheckTrackingIfRequired event in table 83 "Item Journal Line"

## Why do you need this change?

I need to provide better error messages for the user. The current error messages make references to the
"Item Journal Line" record — which is a temporary record for document postings (such as a Sales Order or
Purchase Invoice) — so the user cannot tell from the error message which document line or which specific
item is missing the item tracking (Serial/Lot).

I therefore want to do the check myself and error with a better error message BEFORE the standard code, by
having an `OnBeforCheckTrackingIfRequired(Rec, ItemTrackingSetup)` event at the start.

## Describe the request

Add the following at the start of `CheckTrackingIfRequired`:

```al
OnBeforCheckTrackingIfRequired(Rec, ItemTrackingSetup);
```

Event procedure:

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeCheckTrackingIfRequired(ItemJournalLine: Record "Item Journal Line"; ItemTrackingSetup: Record "Item Tracking Setup");
begin
end;
```

## Scope

- File: `ItemJournalLine.Table.al`
- This table is present in the W1, APAC, CH, ES, FR, GB, IT and RU layers (each keeps its own copy). The
  identical change must be applied to all eight layer files (W1, APAC, CH, ES, FR, GB, IT, RU).
