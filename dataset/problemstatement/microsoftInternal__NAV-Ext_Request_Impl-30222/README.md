# Extensibility request: IsHandled event before RecreatePurchLines in table 38 "Purchase Header" (Pay-to Vendor No. validation)

## Why do you need this change?

We need an event inside the `OnValidate` trigger of field "Pay-to Vendor No.", to be able to run the
procedure `RecreatePurchLines` only if a custom `if` statement is satisfied or, alternatively, run a custom
procedure. Managing an `IsHandled` variable is the only way to skip `RecreatePurchLines` (when a particular
custom condition is satisfied) and run a custom procedure instead. At the moment there are no other ways to
do that.

### Why an IsHandled event is required

Some custom purchase lines contain additional information that must be preserved when the Pay-to Vendor
changes; executing the standard `RecreatePurchLines(PayToVendorTxt)` would remove or recreate lines in a way
that is not compatible with the custom business process. The extension needs to evaluate a custom condition,
skip the standard call when satisfied, and execute an alternative recreation procedure. The existing
`OnValidatePaytoVendorNoBeforeRecreateLines` event is raised immediately before the call but provides no
`IsHandled` parameter, and the generic `OnBeforeRecreatePurchLinesHandler` inside `RecreatePurchLines()`
is too late and too broad, so the decision must be made at the caller level in this specific validation.

The subscriber also needs `xRec` because the decision depends on comparing the document state before and
after the validation of "Pay-to Vendor No.".

## Describe the request

In the `OnValidate` trigger of field(4; "Pay-to Vendor No."; Code[20]) of table 38 "Purchase Header", raise
a new `IsHandled` event immediately before `RecreatePurchLines(PayToVendorTxt)`:

```al
if (xRec."Buy-from Vendor No." = "Buy-from Vendor No.") and
   (xRec."Pay-to Vendor No." <> "Pay-to Vendor No.")
then begin
    IsHandled := false;
    OnBeforeRecreatePurchLines(IsHandled, Rec, xRec);
    if not IsHandled then
        RecreatePurchLines(PayToVendorTxt);
end;
```

```al
[IntegrationEvent(false, false)]
local procedure OnBeforeRecreatePurchLines(var IsHandled: Boolean; var Rec: Record "Purchase Header"; xRec: Record "Purchase Header")
begin
end;
```

## Scope

- File: `PurchaseHeader.Table.al`
- This table is present in 14 layers (W1, APAC, BE, CH, DACH, ES, FI, GB, IT, NA, NL, NO, RU, SE), each
  keeping its own copy. The identical change must be applied to all 14 layer files.
