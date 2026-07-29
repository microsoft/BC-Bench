# Extensibility request: three extension points in table 39 "Purchase Line"

## Why this change is needed

Table 39 "Purchase Line" runs several pieces of standard logic that an extension currently cannot
skip or replace. In three places there is no event that lets a subscriber apply a custom condition
and, when it is met, run its own logic instead of the standard call:

1. In the `"Location Code"` field `OnValidate` trigger, `PlanPriceCalcByField` is always called for
   items when the location changes; there is no way to suppress it conditionally.
2. In `CopyFromItem`, `GetItemTranslation` is always called when the purchase header has a language
   code; there is no way to skip it and run custom translation handling instead.
3. In `CheckWMS`, `CheckLocationOnWMS` is always called when `CurrFieldNo <> 0`; there is no way to
   suppress that warehouse check conditionally.

We need an extension point before each of these calls so subscribers can plug in custom handling in a
supported, upgrade-safe way.

## Requested change

Add three new integration events to table 39 "Purchase Line", each raised **before** the
corresponding standard call and each using the `IsHandled` pattern so a subscriber that sets
`IsHandled := true` skips the standard call:

1. Before `PlanPriceCalcByField` in the `"Location Code"` `OnValidate` trigger. Pass the
   `Purchase Line` record, `IsHandled` (var), the current field number, and the `xPurchaseLine`
   record.
2. Before `GetItemTranslation` in `CopyFromItem`. Pass the `Purchase Line` record, the `Item` record,
   and `IsHandled` (var).
3. Before `CheckLocationOnWMS` in `CheckWMS`. Pass the `Purchase Line` record, the current field
   number, and `IsHandled` (var). `CheckWMS` needs a local `IsHandled: Boolean` variable added.

Illustrative shape for one of the three (final event names and signatures must follow BC event
conventions):

```al
local procedure CheckWMS()
var
    IsHandled: Boolean;
begin
    IsHandled := false;
    // new integration event raised here, passing Purchase Line, CurrFieldNo, and IsHandled (var)
    if not IsHandled then
        if CurrFieldNo <> 0 then
            CheckLocationOnWMS();
    // ...
end;
```

## Scope

- Table 39 "Purchase Line" is kept as a separate copy in many country/region layers. All three
  events must be added consistently to **every** layer that keeps a copy of this table:
  - `App/Layers/W1/BaseApp/Purchases/Document/PurchaseLine.Table.al`
  - and the same file in the APAC, BE, CH, DACH, ES, FI, GB, IT, NA, NL, NO, RU, and SE layers.
- That is 14 layer copies in total, so exactly 14 files change.
