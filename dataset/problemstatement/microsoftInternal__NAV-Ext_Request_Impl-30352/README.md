# Extensibility request: add SkipNewExpirationDateCheck to OnCheckExpirationDateOnAfterCalcSumLot in codeunit 22 "Item Jnl.-Post Line"

## Why do you need this change?

I would like an additional `var` parameter called `SkipNewExpirationDateCheck` added to the
`OnCheckExpirationDateOnAfterCalcSumLot` event, and if this is set to `true` by the subscriber, to then skip
the `TestField` on the "New Expiration Date" field.

Note: as this is an integration event, adding extra parameters is not a breaking change, and existing
subscribers will be unaffected.

## Describe the request

Existing code:

```al
OnCheckExpirationDateOnAfterCalcSumLot(SumLot, SignFactor, TempTrackingSpecification);
if (SumOfEntries > 0) and
   ((SumOfEntries <> SumLot) or (TempTrackingSpecification."New Lot No." <> TempTrackingSpecification."Lot No.")
   or (TempTrackingSpecification."New Package No." <> TempTrackingSpecification."Package No."))
then
    TempTrackingSpecification.TestField("New Expiration Date", ExistingExpirationDate);
```

Amended/proposed code:

```al
SkipNewExpirationDateCheck := false;
OnCheckExpirationDateOnAfterCalcSumLot(SumLot, SignFactor, TempTrackingSpecification, SkipNewExpirationDateCheck);
if (not SkipNewExpirationDateCheck) and (SumOfEntries > 0) and
   ((SumOfEntries <> SumLot) or (TempTrackingSpecification."New Lot No." <> TempTrackingSpecification."Lot No.")
   or (TempTrackingSpecification."New Package No." <> TempTrackingSpecification."Package No."))
then
    TempTrackingSpecification.TestField("New Expiration Date", ExistingExpirationDate);
```

Updated event signature:

```al
[IntegrationEvent(false, false)]
local procedure OnCheckExpirationDateOnAfterCalcSumLot(var SumLot: Decimal; SignFactor: Integer; var TempTrackingSpecification: Record "Tracking Specification" temporary; var SkipNewExpirationDateCheck: Boolean)
begin
end;
```

## Scope

- File: `ItemJnlPostLine.Codeunit.al`
- This codeunit is present in the W1, APAC, CH, ES, IT and RU layers (each keeps its own copy). The
  identical change must be applied to all six layer files (W1, APAC, CH, ES, IT, RU).
